

# ⚡ ElectON — Blockchain-Verified Online Voting on Solana

**Transparent. Anonymous. Verifiable.**

A full-stack decentralized voting platform that brings trustworthy elections to student councils, clubs, and institutions — with every ballot cryptographically committed to the Solana blockchain.

[![Solana](https://img.shields.io/badge/Solana-Devnet-9945FF?logo=solana&logoColor=white)](https://explorer.solana.com/address/HLB1EmZyXZ4vqjkh7qPafjWDxQkMfaLiFExQkE2e5G7w?cluster=devnet)
[![Anchor](https://img.shields.io/badge/Anchor-0.32-blue)](https://www.anchor-lang.com/)
[![Django](https://img.shields.io/badge/Django-5.x-092E20?logo=django)](https://djangoproject.com)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://python.org)

[Demo Video](https://youtu.be/FyVZHB8KP8A?si=mfzll7D3c5vFUdgU) · [Solana Explorer](https://explorer.solana.com/address/HLB1EmZyXZ4vqjkh7qPafjWDxQkMfaLiFExQkE2e5G7w?cluster=devnet)



---

## 🎯 Problem Statement

Elections in student councils, clubs, and small institutions are plagued by:

- **Distrust** — Voters don't know if results were tampered after submission
- **Opacity** — No way to independently verify that your vote was counted
- **Identity leaks** — Existing digital voting tools can link votes back to voters
- **Cost** — Traditional blockchain voting is too expensive for small organizations

**ElectON solves all four.** Every vote is anonymized with SHA-256 hashing, committed to Solana via Merkle proofs, and publicly verifiable — while keeping per-vote costs under $0.001.

---

## ✨ Key Features

| Feature | How It Works |
|---------|-------------|
| 🗳️ **Anonymous Voting** | Votes are permanently disconnected from voter identity via SHA-256 hashing with a per-deployment salt. No foreign key exists between Vote and VoterCredential — mathematically impossible to link. |
| ⛓️ **Solana Blockchain Verification** | A Merkle tree of voter hashes is computed off-chain; only the 32-byte root is stored on-chain. Each vote includes a Merkle proof verified by the Anchor program. |
| 🔍 **Public Verifiability** | Anyone can verify a specific ballot was recorded on-chain via Solana Explorer. DB-vs-chain integrity comparison available for full audits. |
| 🌲 **Merkle Tree Architecture** | Compact on-chain footprint — O(1) root storage instead of O(n) voter registration. Reduces Solana rent costs by ~95% compared to storing individual voter hashes. |
| 💰 **Rent Recovery** | After elections end, `finalize_election` → `close_election` recovers the full rent deposit back to the admin wallet. Zero net cost for account storage. |
| 📊 **Real-Time Results** | Live vote counts with turnout statistics, pie/bar/timeline charts, and downloadable PDF reports. |
| 🔐 **Enterprise Security** | PBKDF2-SHA256 passwords, hashed tokens, progressive rate limiting, admin 2FA, CSP headers, 19-type audit logging. |
| 🌙 **Modern UI** | Apple-inspired glassmorphism design with dark mode, responsive layout, and accessibility support. |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client (Browser)                         │
│         Bootstrap 5.3 + Font Awesome 6.5 + ES Modules           │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS
┌──────────────────────────────▼──────────────────────────────────┐
│                     Django 5.x + DRF                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ Accounts │ │Elections │ │Candidates│ │     Voting       │   │
│  │ (auth,   │ │(CRUD,    │ │(CRUD,    │ │(credentials,     │   │
│  │  2FA)    │ │lifecycle)│ │ images)  │ │ anonymous votes) │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ Results  │ │ Notify   │ │  Audit   │ │   Blockchain     │   │
│  │(charts,  │ │(Brevo    │ │(19 types)│ │(Anchor program,  │   │
│  │  PDFs)   │ │ +Azure)  │ │          │ │ Merkle proofs)   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    REST API (DRF)                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────┬─────────────────┬────────────────────┬───────────────┘
           │                 │                    │
    ┌──────▼──────┐  ┌───────▼──────┐  ┌──────────▼──────────┐
    │ PostgreSQL  │  │    Redis     │  │   Solana Devnet     │
    │ (data)      │  │ (cache/queue)│  │ (vote commitments)  │
    └─────────────┘  └──────────────┘  └─────────────────────┘
```

---

## ⛓️ Solana Integration (Deep Dive)

### On-Chain Program: `electon_voting`

**Program ID:** [`HLB1EmZyXZ4vqjkh7qPafjWDxQkMfaLiFExQkE2e5G7w`](https://explorer.solana.com/address/HLB1EmZyXZ4vqjkh7qPafjWDxQkMfaLiFExQkE2e5G7w?cluster=devnet)

Written in Rust using the **Anchor framework (v0.32)**, the on-chain program exposes 4 instructions:

| Instruction | Purpose | Security |
|------------|---------|----------|
| `initialize_election` | Create PDA with Merkle root, config hash, candidate slots | Authority-signed, UUID-seeded PDA |
| `cast_vote` | Verify Merkle proof, record vote in bitfield + tally array | Time-window enforcement, double-vote guard, proof verification |
| `finalize_election` | Lock results after end time | Must be past `end_time`, idempotent |
| `close_election` | Refund rent deposit to admin wallet | Must be finalized first |

### Merkle Tree Architecture

```
              ┌──────────────┐
              │  Merkle Root │ ← stored on-chain (32 bytes)
              └──────┬───────┘
                ┌────┴────┐
            ┌───┴───┐ ┌───┴───┐
            │ H(AB) │ │ H(CD) │
            └───┬───┘ └───┬───┘
           ┌────┴──┐  ┌───┴───┐
           │       │  │       │
        H(voter₁) H(voter₂) H(voter₃) H(voter₄)
```

- **Off-chain:** Django builds a SHA-256 Merkle tree from all voter hashes
- **On-chain:** Only the 32-byte root is stored (saves ~99% rent vs. storing all hashes)
- **At vote time:** Voter provides their Merkle proof; the Anchor program verifies it against the root
- **Double-vote prevention:** Compact bitfield (1 bit per voter) checked on every `cast_vote`

### Vote Flow

```
1. Admin creates election → Django computes Merkle tree of voter hashes
2. initialize_election(merkle_root, config_hash, ...) → PDA created on Solana
3. Voter casts ballot → Django generates Merkle proof for this voter
4. cast_vote(voter_index, voter_hash, proof, votes) → On-chain verification & recording
5. Election ends → finalize_election() → close_election() → rent recovered
6. Anyone can verify votes via Solana Explorer transaction signatures
```

### On-Chain State Layout

```rust
pub struct ElectionState {
    authority: Pubkey,           // Admin wallet (32 bytes)
    election_uuid: [u8; 16],    // Maps to Django UUID
    config_hash: [u8; 32],      // Tamper-detection hash
    merkle_root: [u8; 32],      // Voter eligibility proof
    voted_bitfield: Vec<u8>,    // 1 bit per voter (compact!)
    vote_counts: Vec<u32>,      // Flat tally array
    candidates_per_post: Vec<u8>,
    // ... timestamps, flags, totals
}
```

### Cost Analysis

| Operation | Cost |
|-----------|------|
| Deploy election (100 voters, 5 posts) | ~0.003 SOL rent (recovered on close) |
| Cast a single vote | 0.000005 SOL (~$0.0007) |
| 1,000 votes across 10 elections | ~0.05 SOL (~$7) |
| Election close (rent recovery) | **Full refund** of deployment rent |

---

## 🛡️ Security Architecture

| Layer | Implementation |
|-------|---------------|
| **Vote Anonymization** | `voter_hash = SHA-256(credential_id + election_uuid + SALT)` — irreversible, no FK from Vote → VoterCredential |
| **On-chain Verification** | Merkle proof + bitfield double-vote guard + time-window enforcement |
| **Authentication** | Session-based with admin 2FA after suspicious login activity |
| **Passwords** | PBKDF2-SHA256 (Django default), never stored in plaintext |
| **Rate Limiting** | Progressive per-action: login 5/5min, voter login API 10/min |
| **Audit Trail** | 19 action types logged with IP, user agent, and JSON details |
| **Transport** | HSTS (1 year, preload), TLS 1.2+, secure cookies, Content Security Policy |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Blockchain** | Solana (Anchor 0.32, Rust), solana-py, anchorpy, solders |
| **Backend** | Python 3.13, Django 5.x, Django REST Framework, Celery, Gunicorn |
| **Database** | PostgreSQL 16 (prod) / SQLite (dev) |
| **Cache & Queue** | Redis 7 |
| **Email** | Brevo transactional API (primary) → Azure Communication Services → SMTP fallback |
| **Storage** | Cloudflare R2 (S3-compatible) for candidate images |
| **Frontend** | Bootstrap 5.3, Font Awesome 6.5, ES Modules, glassmorphism CSS |
| **Infrastructure** | Docker Compose, Nginx, Let's Encrypt TLS, GitHub Actions CI/CD |
| **Monitoring** | Sentry (optional) |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+ *(only if building the Solana program)*
- Anchor CLI 0.32+ *(only if building the Solana program)*

### Quick Start (Development)

```bash
# Clone the repository
git clone https://github.com/your-username/electon.git
cd electon

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.production.example .env
# Edit .env — set SECRET_KEY, VOTE_ANONYMIZATION_SALT at minimum

# Set up database
python manage.py migrate
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

### First Steps

1. Register at `/accounts/register/`
2. Verify email (check terminal output in dev mode)
3. Create an election → Add posts → Add candidates
4. Import voters via CSV (header: `email`, optionally `name`)
5. Send voter invitations
6. Launch the election
7. Voters log in at `/voting/login/<uuid>/` with their emailed credentials
8. Results with blockchain verification links at `/results/<uuid>/`

### Docker (Production)

```bash
# Configure environment
cp .env.production.example .env
# Fill in all values

# Build and start all services
docker compose build
docker compose up -d

# Initialize database
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

---

## 📁 Project Structure

```
electon/
├── solana-program/                    # 🦀 Rust Anchor program (on-chain logic)
│   └── programs/electon_voting/
│       └── src/lib.rs                 # 4 instructions, 465 lines of Rust
│
├── apps/                              # 🐍 Django applications (9 modules)
│   ├── blockchain/                    # Solana integration layer
│   │   ├── services/
│   │   │   ├── program_service.py     # Anchor program interactions (anchorpy)
│   │   │   ├── solana_client.py       # RPC wrapper with retry & commitment control
│   │   │   ├── verification_service.py# Public vote verification
│   │   │   └── merkle_tree.py         # SHA-256 Merkle tree implementation
│   │   └── contracts/
│   │       └── electon_voting.json    # Anchor IDL
│   ├── accounts/                      # Auth, registration, email verification, 2FA
│   ├── elections/                     # Election CRUD, 6-state lifecycle
│   ├── candidates/                    # Candidate management, image processing
│   ├── voting/                        # Voter credentials, anonymous vote casting
│   ├── results/                       # Charts (matplotlib), PDF reports
│   ├── notifications/                 # Multi-provider email routing
│   ├── audit/                         # Security audit logging
│   └── api/                           # DRF REST API
│
├── templates/                         # Django HTML templates
├── static/                            # CSS (glassmorphism) + JS (ES modules)
├── docker-compose.yml                 # Full production stack
├── Dockerfile                         # Multi-stage production build
└── .github/workflows/                 # CI (lint+test) + CD (Docker deploy)
```

---

## 🗳️ Election Lifecycle

```
Draft ──launch──▶ Scheduled ──start_time──▶ Active ──end_time──▶ Ended
                       │                      │
                       └────── Paused ─────────┘
                                │
                          Terminated (admin action, irreversible)
```

---

## 🌐 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/health/` | None | Health check |
| `GET` | `/api/elections/` | Admin | List admin's elections |
| `GET` | `/api/elections/<uuid>/` | Admin | Election detail with posts/candidates |
| `GET` | `/api/elections/<uuid>/results/` | Public | Aggregate results |
| `POST` | `/api/voting/login/` | None | Voter credential login (rate-limited) |
| `POST` | `/api/voting/cast/` | Voter session | Cast votes with blockchain commit |
| `GET` | `/api/blockchain/verify/<uuid>/` | None | On-chain vote verification |

---

## 🌍 Civic Tech & Broader Impact

ElectON directly addresses the need for **transparent, verifiable governance technology**:

- **Trust in elections** — Every ballot is committed to Solana with a verifiable transaction signature. Results cannot be altered after submission.
- **Privacy-preserving participation** — Votes are permanently anonymized via one-way SHA-256 hashing. Even database administrators cannot link votes to voters.
- **Accessible governance** — Student councils, clubs, and local organizations can run trustworthy elections without expensive infrastructure.
- **Cost-effective** — Merkle tree architecture keeps on-chain costs minimal. Rent recovery means election infrastructure has near-zero net blockchain cost.
- **Nepali innovation on Solana** — Built by Nepali developers to put Nepali tech talent on the Solana map and showcase how blockchain can power governance solutions in emerging tech ecosystems.

This aligns with the bounty's emphasis on **Janamat, open governance, and civic data technology** — ElectON is a working prototype of how Solana can make everyday governance more transparent and trustworthy.

---

## 👥 Team

| Member | Role |
|--------|------|
| **Sujal Paudel** | Solo Developer & Architect |

---

## 📝 License

Copyright © 2026 Sujal Paudel. All rights reserved.

This source code is made publicly available for review and educational purposes only. No permission is granted to copy, modify, distribute, or use this software for commercial or non-commercial purposes without explicit written consent from the author.

---

<div align="center">

**Built with ❤️ for the Superteam Nepal Solana Bounty**

[Solana](https://solana.com) · [Anchor](https://anchor-lang.com) · [Django](https://djangoproject.com)

</div>
