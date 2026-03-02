"""Merkle tree helpers for ElectON voter registration.

Leaf hashes are 32-byte SHA-256 digests of a voter credential identifier.
The same SHA-256-based pair-hashing is used by the on-chain Rust program so
that proofs generated here verify correctly on Solana.

Algorithm
---------
1. Start with a list of 32-byte leaf hashes (one per eligible voter).
2. At each level, pair adjacent nodes and hash them together.
3. If the number of nodes at a level is odd, duplicate the last node.
4. Repeat until a single 32-byte root remains.

The Merkle tree is NOT stored anywhere — it is always rebuilt from the
sorted list of voter hashes stored on ``VoterCredential`` records.

Usage
-----
    leaves = [bytes.fromhex(cred.blockchain_voter_hash) for cred in creds]
    root, layers = build_merkle_tree(leaves)
    proof = get_merkle_proof(layers, voter_index)
    ok = verify_merkle_proof(leaf=leaves[voter_index], proof=proof,
                             leaf_index=voter_index, root=root)
"""

from __future__ import annotations

import hashlib
from typing import List, Tuple


def _hash_pair(left: bytes, right: bytes) -> bytes:
    """SHA-256 of left || right.  Matches Rust ``hash_pair`` exactly."""
    return hashlib.sha256(left + right).digest()


def build_merkle_tree(
    leaves: List[bytes],
) -> Tuple[bytes, List[List[bytes]]]:
    """Build a complete Merkle tree from a list of 32-byte leaf hashes.

    Parameters
    ----------
    leaves:
        Non-empty list of 32-byte SHA-256 digests sorted by voter index.

    Returns
    -------
    root:
        The 32-byte Merkle root (the value committed on-chain).
    layers:
        All layers of the tree from leaves (index 0) up to the root
        (index -1).  Each layer is a list of 32-byte node hashes.

    Raises
    ------
    ValueError
        If ``leaves`` is empty or any leaf is not exactly 32 bytes.
    """
    if not leaves:
        raise ValueError("Cannot build a Merkle tree from an empty leaf list.")
    for i, leaf in enumerate(leaves):
        if len(leaf) != 32:
            raise ValueError(
                f"Leaf at index {i} is {len(leaf)} bytes; expected 32."
            )

    # Layer 0 = leaf level
    layers: List[List[bytes]] = [list(leaves)]

    while len(layers[-1]) > 1:
        current = layers[-1]
        # Duplicate last node if the level count is odd (standard padding)
        if len(current) % 2 == 1:
            current = current + [current[-1]]
        next_level: List[bytes] = []
        for i in range(0, len(current), 2):
            next_level.append(_hash_pair(current[i], current[i + 1]))
        layers.append(next_level)

    root = layers[-1][0]
    return root, layers


def get_merkle_proof(
    layers: List[List[bytes]],
    leaf_index: int,
) -> List[bytes]:
    """Return the Merkle proof (list of sibling hashes) for a given leaf.

    Parameters
    ----------
    layers:
        The tree layers as returned by ``build_merkle_tree``.
    leaf_index:
        0-based index of the target leaf in the leaf layer.

    Returns
    -------
    A list of 32-byte sibling hashes from leaf level up to (but not
    including) the root.  Pass these directly to the Solana ``cast_vote``
    instruction.
    """
    proof: List[bytes] = []
    idx = leaf_index

    for level, layer in enumerate(layers[:-1]):  # ignore root layer
        # If the current layer was padded, the padded layer has one extra node
        # but we address siblings relative to the original layer length.
        padded = list(layer)
        if len(padded) % 2 == 1:
            padded = padded + [padded[-1]]

        if idx % 2 == 0:
            # idx is a left node → sibling is idx + 1
            sibling_idx = idx + 1
        else:
            # idx is a right node → sibling is idx - 1
            sibling_idx = idx - 1

        proof.append(padded[sibling_idx])
        idx //= 2  # move to parent index

    return proof


def verify_merkle_proof(
    leaf: bytes,
    proof: List[bytes],
    leaf_index: int,
    root: bytes,
) -> bool:
    """Verify that ``leaf`` belongs to the tree with the given ``root``.

    This is a pure-Python reference implementation of the on-chain Rust
    verification loop — useful for unit tests and debugging.

    Parameters
    ----------
    leaf:
        The 32-byte leaf hash for the voter being verified.
    proof:
        Ordered list of sibling hashes (from leaf level up to root).
    leaf_index:
        0-based index of the leaf; determines left/right ordering at each
        level.
    root:
        The expected 32-byte Merkle root.

    Returns
    -------
    ``True`` if the proof is valid, ``False`` otherwise.
    """
    if len(leaf) != 32 or len(root) != 32:
        return False

    computed = leaf
    idx = leaf_index
    for sibling in proof:
        if idx % 2 == 0:
            computed = _hash_pair(computed, sibling)
        else:
            computed = _hash_pair(sibling, computed)
        idx //= 2

    return computed == root
