//! ElectON on-chain election program — Merkle Tree model.
//!
//! Instructions:
//!   • initialize_election — create the election state PDA with Merkle root
//!   • cast_vote           — verify Merkle proof and record vote selections
//!   • finalize_election   — mark election as ready for account closure
//!   • close_election      — close PDA account and refund rent deposit
//!
//! The `register_voters` instruction no longer exists. Instead, Django builds
//! a Merkle tree of voter hashes off-chain and stores only the 32-byte root
//! on-chain. Each voter provides a Merkle proof when casting their vote.
//! After the election ends, `finalize_election` followed by `close_election`
//! recovers the rent deposit.

use anchor_lang::prelude::*;
use sha2::{Digest, Sha256};

declare_id!("HLB1EmZyXZ4vqjkh7qPafjWDxQkMfaLiFExQkE2e5G7w");

// ─────────────────────────────────────────────────────────────────────────────
//  Instructions
// ─────────────────────────────────────────────────────────────────────────────

#[program]
pub mod electon_voting {
    use super::*;

    /// Create and initialise the on-chain election state.
    ///
    /// The Merkle root of all eligible voter hashes is passed instead of
    /// the individual hashes.  Account space is sized precisely based on
    /// the actual number of voters, posts and candidates —
    /// no MAX_* over-allocation.
    ///
    /// # Arguments
    /// * `election_uuid`       – 16-byte UUID (Python `uuid.bytes`)
    /// * `config_hash`         – 32-byte SHA-256 of the election config snapshot
    /// * `merkle_root`         – 32-byte root of the voter-hash Merkle tree
    /// * `num_voters`          – Total number of eligible voters
    /// * `num_posts`           – Number of posts (races) in the election
    /// * `candidates_per_post` – Candidate count per post (len == num_posts)
    /// * `start_time`          – Unix timestamp (seconds)
    /// * `end_time`            – Unix timestamp (seconds)
    pub fn initialize_election(
        ctx: Context<InitializeElection>,
        election_uuid: Vec<u8>,
        config_hash: Vec<u8>,
        merkle_root: Vec<u8>,
        num_voters: u32,
        num_posts: u8,
        candidates_per_post: Vec<u8>,
        start_time: i64,
        end_time: i64,
    ) -> Result<()> {
        require!(election_uuid.len() == 16, ElectonError::InvalidUuid);
        require!(config_hash.len() == 32, ElectonError::InvalidConfigHash);
        require!(merkle_root.len() == 32, ElectonError::InvalidMerkleRoot);
        require!(
            candidates_per_post.len() == num_posts as usize,
            ElectonError::PostCountMismatch
        );
        require!(start_time < end_time, ElectonError::InvalidTimeRange);
        require!(num_voters > 0, ElectonError::NoVoters);

        let state = &mut ctx.accounts.election_state;
        state.authority = ctx.accounts.authority.key();

        let uuid_arr: [u8; 16] = election_uuid
            .try_into()
            .map_err(|_| error!(ElectonError::InvalidUuid))?;
        let hash_arr: [u8; 32] = config_hash
            .try_into()
            .map_err(|_| error!(ElectonError::InvalidConfigHash))?;
        let root_arr: [u8; 32] = merkle_root
            .try_into()
            .map_err(|_| error!(ElectonError::InvalidMerkleRoot))?;

        state.election_uuid = uuid_arr;
        state.config_hash = hash_arr;
        state.merkle_root = root_arr;
        state.num_voters = num_voters;
        state.num_posts = num_posts;
        state.start_time = start_time;
        state.end_time = end_time;
        state.is_finalized = false;
        state.total_votes = 0;
        state.bump = ctx.bumps.election_state;

        let total_candidates: u16 = candidates_per_post
            .iter()
            .map(|&c| c as u16)
            .sum();
        state.total_candidates = total_candidates;
        state.candidates_per_post = candidates_per_post;

        // All-zero bitfield: 1 bit per voter, 0 = has not voted
        state.voted_bitfield = vec![0u8; ((num_voters as usize + 7) / 8)];
        // All-zero tallies: one u32 per candidate slot
        state.vote_counts = vec![0u32; total_candidates as usize];

        msg!(
            "Election initialised: {} voters, {} posts, {} candidate slots",
            num_voters,
            num_posts,
            total_candidates,
        );
        Ok(())
    }

    /// Cast a vote on behalf of a registered voter.
    ///
    /// Security checks (all enforced on-chain):
    ///   1. Authority must sign (only the Django server can submit votes)
    ///   2. Election must be within the active time window
    ///   3. Voter index must be in range
    ///   4. Voter must not have already voted (bitfield check)
    ///   5. Merkle proof must verify the voter hash against the stored root
    ///   6. Each post may appear at most once in `votes` (no vote inflation)
    ///
    /// # Arguments
    /// * `voter_index`   – 0-based position of this voter in the Merkle tree
    /// * `voter_hash`    – 32-byte SHA-256 leaf that was committed to the tree
    /// * `merkle_proof`  – Sibling hashes from leaf level up to the root
    /// * `votes`         – One `VoteEntry` per voted post
    pub fn cast_vote(
        ctx: Context<CastVote>,
        voter_index: u32,
        voter_hash: Vec<u8>,
        merkle_proof: Vec<[u8; 32]>,
        votes: Vec<VoteEntry>,
    ) -> Result<()> {
        require!(voter_hash.len() == 32, ElectonError::InvalidVoterHash);

        let state = &mut ctx.accounts.election_state;

        // ── 1. Time enforcement (S-02) ──────────────────────────────────
        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp >= state.start_time,
            ElectonError::ElectionNotStarted
        );
        require!(
            clock.unix_timestamp <= state.end_time,
            ElectonError::ElectionEnded
        );

        // ── 2. Voter index bounds ────────────────────────────────────────
        require!(
            voter_index < state.num_voters,
            ElectonError::VoterNotRegistered
        );

        // ── 3. Double-vote guard via bitfield ────────────────────────────
        let byte_idx = (voter_index / 8) as usize;
        let bit_idx  = (voter_index % 8) as u8;
        require!(
            state.voted_bitfield[byte_idx] & (1u8 << bit_idx) == 0,
            ElectonError::AlreadyVoted
        );

        // ── 4. Merkle proof verification ─────────────────────────────────
        let leaf: [u8; 32] = voter_hash
            .try_into()
            .map_err(|_| error!(ElectonError::InvalidVoterHash))?;
        let mut computed = leaf;
        let mut idx = voter_index;
        for sibling in merkle_proof.iter() {
            computed = if idx % 2 == 0 {
                hash_pair(&computed, sibling)
            } else {
                hash_pair(sibling, &computed)
            };
            idx /= 2;
        }
        require!(
            computed == state.merkle_root,
            ElectonError::InvalidMerkleProof
        );

        // ── 5. Record vote selections, duplicate-post guard (S-03) ───────
        let cpp = state.candidates_per_post.clone();
        let mut seen_posts = vec![false; state.num_posts as usize];

        for vote in votes.iter() {
            let post_idx = vote.post_index as usize;
            require!(
                post_idx < state.num_posts as usize,
                ElectonError::InvalidPostIndex
            );
            require!(
                !seen_posts[post_idx],
                ElectonError::DuplicatePostVote
            );
            seen_posts[post_idx] = true;

            let offset: usize = cpp[..post_idx].iter().map(|&c| c as usize).sum();
            let cand_idx = vote.candidate_index as usize;
            require!(
                cand_idx < cpp[post_idx] as usize,
                ElectonError::InvalidCandidateIndex
            );

            state.vote_counts[offset + cand_idx] = state.vote_counts[offset + cand_idx]
                .checked_add(1)
                .ok_or(ElectonError::VoteOverflow)?;
        }

        // ── 6. Mark voter as voted in bitfield ───────────────────────────
        state.voted_bitfield[byte_idx] |= 1u8 << bit_idx;
        state.total_votes += 1;

        msg!("Vote cast — total votes: {}", state.total_votes);
        Ok(())
    }

    /// Mark the election as finalised so `close_election` can proceed.
    ///
    /// Must be called after `end_time` has passed. Django should archive
    /// the on-chain state to the database between this call and `close_election`.
    pub fn finalize_election(ctx: Context<FinalizeElection>) -> Result<()> {
        let state = &mut ctx.accounts.election_state;
        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp > state.end_time,
            ElectonError::ElectionNotEnded
        );
        require!(!state.is_finalized, ElectonError::AlreadyFinalized);
        state.is_finalized = true;
        msg!("Election finalised — total votes: {}", state.total_votes);
        Ok(())
    }

    /// Close the election state account and refund all rent to the authority.
    ///
    /// Requires:
    ///   • Election must be past end_time
    ///   • Election must have been finalised via `finalize_election`
    ///   • Anchor's `close = authority` constraint performs the lamport transfer
    pub fn close_election(ctx: Context<CloseElection>) -> Result<()> {
        let state = &ctx.accounts.election_state;
        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp > state.end_time,
            ElectonError::ElectionNotEnded
        );
        require!(
            state.is_finalized,
            ElectonError::ElectionNotFinalized
        );
        msg!(
            "Election account closed — rent refunded to {}",
            ctx.accounts.authority.key()
        );
        Ok(())
        // Anchor's `close = authority` in the Accounts struct handles the
        // lamport transfer and zeroes the account data automatically.
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────────

/// SHA-256 of two 32-byte values concatenated (left ‖ right).
/// Matches the Python `_hash_pair` in `merkle_tree.py` exactly.
fn hash_pair(left: &[u8; 32], right: &[u8; 32]) -> [u8; 32] {
    Sha256::new()
        .chain_update(left.as_ref())
        .chain_update(right.as_ref())
        .finalize()
        .into()
}

// ─────────────────────────────────────────────────────────────────────────────
//  Account constraint contexts
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Accounts)]
#[instruction(
    election_uuid: Vec<u8>,
    _config_hash: Vec<u8>,
    _merkle_root: Vec<u8>,
    num_voters: u32,
    num_posts: u8,
    candidates_per_post: Vec<u8>,
)]
pub struct InitializeElection<'info> {
    #[account(
        init,
        payer = authority,
        space = ElectionState::space(
            num_voters,
            candidates_per_post.iter().map(|&c| c as u16).sum::<u16>(),
            num_posts,
        ),
        seeds = [b"election", election_uuid.as_slice()],
        bump
    )]
    pub election_state: Account<'info, ElectionState>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// S-01 fix: authority must sign every cast_vote transaction.
#[derive(Accounts)]
pub struct CastVote<'info> {
    #[account(mut, has_one = authority)]
    pub election_state: Account<'info, ElectionState>,
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct FinalizeElection<'info> {
    #[account(mut, has_one = authority)]
    pub election_state: Account<'info, ElectionState>,
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct CloseElection<'info> {
    /// `close = authority` transfers all lamports to authority and zeroes the account.
    #[account(mut, close = authority, has_one = authority)]
    pub election_state: Account<'info, ElectionState>,
    #[account(mut)]
    pub authority: Signer<'info>,
}

// ─────────────────────────────────────────────────────────────────────────────
//  On-chain state
// ─────────────────────────────────────────────────────────────────────────────

#[account]
pub struct ElectionState {
    /// Deployer / admin wallet  (32 bytes)
    pub authority: Pubkey,
    /// 16-byte UUID matching the Django election record
    pub election_uuid: [u8; 16],
    /// SHA-256 of the election configuration snapshot for tamper detection
    pub config_hash: [u8; 32],
    /// Merkle root of all eligible voter hashes (32 bytes — replaces voter_hashes Vec)
    pub merkle_root: [u8; 32],
    /// Total number of eligible voters (used for bitfield sizing and bounds)
    pub num_voters: u32,
    /// Number of posts (races)
    pub num_posts: u8,
    /// Sum of candidates_per_post
    pub total_candidates: u16,
    /// Unix timestamps (seconds)
    pub start_time: i64,
    pub end_time: i64,
    /// True after `finalize_election` is called; required before `close_election`
    pub is_finalized: bool,
    /// PDA bump seed
    pub bump: u8,
    /// Total ballots successfully cast
    pub total_votes: u64,
    /// Bitfield: 1 bit per voter. Bit N = 1 means voter N has already voted.
    pub voted_bitfield: Vec<u8>,
    /// Flat vote tallies: [post0_cand0, post0_cand1, …, postN_candM]
    pub vote_counts: Vec<u32>,
    /// Candidate count per post (length == num_posts)
    pub candidates_per_post: Vec<u8>,
}

impl ElectionState {
    /// Compute the exact account space for a given election configuration.
    ///
    /// Layout:
    /// ```
    ///   8   discriminator
    ///  32   authority (Pubkey)
    ///  16   election_uuid
    ///  32   config_hash
    ///  32   merkle_root
    ///   4   num_voters (u32)
    ///   1   num_posts (u8)
    ///   2   total_candidates (u16)
    ///   8   start_time (i64)
    ///   8   end_time (i64)
    ///   1   is_finalized (bool)
    ///   1   bump (u8)
    ///   8   total_votes (u64)
    ///   4 + ceil(num_voters / 8)           voted_bitfield Vec<u8>
    ///   4 + total_candidates * 4           vote_counts Vec<u32>
    ///   4 + num_posts                      candidates_per_post Vec<u8>
    /// ```
    pub fn space(num_voters: u32, total_candidates: u16, num_posts: u8) -> usize {
        let bitfield_bytes = ((num_voters as usize) + 7) / 8;
        8       // discriminator
        + 32    // authority
        + 16    // election_uuid
        + 32    // config_hash
        + 32    // merkle_root
        + 4     // num_voters
        + 1     // num_posts
        + 2     // total_candidates
        + 8     // start_time
        + 8     // end_time
        + 1     // is_finalized
        + 1     // bump
        + 8     // total_votes
        + 4 + bitfield_bytes                    // voted_bitfield
        + 4 + (total_candidates as usize) * 4  // vote_counts
        + 4 + (num_posts as usize)              // candidates_per_post
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Shared types
// ─────────────────────────────────────────────────────────────────────────────

/// A single vote selection for one post within a `cast_vote` call.
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct VoteEntry {
    pub post_index: u8,
    pub candidate_index: u8,
}

// ─────────────────────────────────────────────────────────────────────────────
//  Error codes
// ─────────────────────────────────────────────────────────────────────────────

#[error_code]
pub enum ElectonError {
    #[msg("election_uuid must be exactly 16 bytes")]
    InvalidUuid,
    #[msg("config_hash must be exactly 32 bytes")]
    InvalidConfigHash,
    #[msg("merkle_root must be exactly 32 bytes")]
    InvalidMerkleRoot,
    #[msg("candidates_per_post length must equal num_posts")]
    PostCountMismatch,
    #[msg("start_time must be before end_time")]
    InvalidTimeRange,
    #[msg("Election must have at least one voter")]
    NoVoters,
    #[msg("Each voter hash must be exactly 32 bytes")]
    InvalidVoterHash,
    #[msg("Voter index is out of range or voter is not registered")]
    VoterNotRegistered,
    #[msg("Voter has already cast their vote")]
    AlreadyVoted,
    #[msg("Invalid Merkle proof — voter hash not in the registered tree")]
    InvalidMerkleProof,
    #[msg("post_index is out of range")]
    InvalidPostIndex,
    #[msg("candidate_index is out of range for this post")]
    InvalidCandidateIndex,
    #[msg("Duplicate vote for the same post is not allowed")]
    DuplicatePostVote,
    #[msg("Vote count overflow")]
    VoteOverflow,
    #[msg("Election has not started yet")]
    ElectionNotStarted,
    #[msg("Election voting period has ended")]
    ElectionEnded,
    #[msg("Election has not ended yet")]
    ElectionNotEnded,
    #[msg("Election has already been finalised")]
    AlreadyFinalized,
    #[msg("Election must be finalised before closing")]
    ElectionNotFinalized,
}
