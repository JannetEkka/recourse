// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title Recourse
/// @notice A public record for automated welfare decisions.
///
/// Any address can act as an agency. An agency publishes each version of its
/// decision rules before it uses them, seals every batch of decisions as one
/// Merkle root, and answers appeals on the record. Personal data never comes
/// on-chain: a leaf is the hash of a salted receipt that only the person (and
/// the agency) holds.
///
/// A leaf is keccak256(outcome byte ++ receiptHash), where receiptHash is the
/// keccak256 of the receipt's canonical JSON. Putting the outcome in the leaf
/// lets the contract accept appeals against denials only. Leaves are 33 bytes
/// and internal nodes 64, so a node can't pass as a leaf.
contract Recourse {
    uint8 public constant ELIGIBLE = 1;
    uint8 public constant DENIED = 2;

    uint8 public constant OPEN = 0;
    uint8 public constant UPHELD = 1;
    uint8 public constant OVERTURNED = 2;

    struct Ruleset {
        address agency;
        uint64 publishedAt;
        uint64 publishedBlock;
        uint64 retiredAt;
        uint16 responseDays; // how long the agency commits to take to answer an appeal
        bytes32 rulesHash; // keccak256 of the canonical rules file
        string uri; // where anyone can read that file
    }

    struct Stats {
        uint32 batches;
        uint32 decisions;
        uint32 denied;
        uint32 appeals;
        uint32 upheld;
        uint32 overturned;
    }

    struct Batch {
        uint32 rulesetId;
        uint32 count;
        uint32 denied;
        uint64 sealedAt;
        bytes32 root;
    }

    struct Appeal {
        uint32 batchId;
        uint8 status;
        uint64 filedAt;
        uint64 answeredAt;
        address filer;
        bytes32 leaf;
        bytes32 groundsHash; // keccak256 of the appeal letter
        bytes32 answerHash; // keccak256 of the agency's written answer
    }

    mapping(address => string) public agencyName;

    uint32 public rulesetCount;
    mapping(uint32 => Ruleset) public rulesets;
    mapping(uint32 => Stats) public stats;
    mapping(address => mapping(bytes32 => uint32)) public rulesetOfHash;

    uint32 public batchCount;
    mapping(uint32 => Batch) public batches;
    mapping(bytes32 => uint32) public batchOfRoot;

    uint32 public appealCount;
    mapping(uint32 => Appeal) public appeals;
    mapping(bytes32 => uint32) public appealOfLeaf;

    event AgencyNamed(address indexed agency, string name);
    event RulesetPublished(
        uint32 indexed id, address indexed agency, bytes32 rulesHash, string uri, uint16 responseDays
    );
    event RulesetRetired(uint32 indexed id);
    event BatchSealed(uint32 indexed id, uint32 indexed rulesetId, bytes32 root, uint32 count, uint32 denied);
    event AppealFiled(uint32 indexed id, uint32 indexed batchId, bytes32 leaf, address filer, bytes32 groundsHash);
    event AppealAnswered(uint32 indexed id, uint8 status, bytes32 answerHash);

    /// @notice An agency names itself once, so the public page can say who it is.
    function nameAgency(string calldata name) external {
        require(bytes(agencyName[msg.sender]).length == 0, "already named");
        require(bytes(name).length > 0 && bytes(name).length <= 96, "bad name");
        agencyName[msg.sender] = name;
        emit AgencyNamed(msg.sender, name);
    }

    /// @notice Publish a version of the decision rules. It can be used from the next block on.
    function publishRuleset(bytes32 rulesHash, string calldata uri, uint16 responseDays)
        external
        returns (uint32 id)
    {
        require(bytes(agencyName[msg.sender]).length != 0, "name the agency first");
        require(rulesHash != bytes32(0), "empty hash");
        require(responseDays > 0 && responseDays <= 365, "bad response days");
        require(rulesetOfHash[msg.sender][rulesHash] == 0, "already published");
        id = ++rulesetCount;
        rulesets[id] = Ruleset({
            agency: msg.sender,
            publishedAt: uint64(block.timestamp),
            publishedBlock: uint64(block.number),
            retiredAt: 0,
            responseDays: responseDays,
            rulesHash: rulesHash,
            uri: uri
        });
        rulesetOfHash[msg.sender][rulesHash] = id;
        emit RulesetPublished(id, msg.sender, rulesHash, uri, responseDays);
    }

    /// @notice Stop using a ruleset. Its record and its appeals stay.
    function retireRuleset(uint32 id) external {
        Ruleset storage r = rulesets[id];
        require(r.agency == msg.sender, "not the agency");
        require(r.retiredAt == 0, "already retired");
        r.retiredAt = uint64(block.timestamp);
        emit RulesetRetired(id);
    }

    /// @notice Seal a batch of decisions made under a published ruleset.
    function sealBatch(uint32 rulesetId, bytes32 root, uint32 count, uint32 denied) external returns (uint32 id) {
        Ruleset storage r = rulesets[rulesetId];
        require(r.agency == msg.sender, "not the agency");
        require(r.retiredAt == 0, "ruleset retired");
        require(r.publishedBlock < block.number, "publish the rules first");
        require(root != bytes32(0) && count > 0 && denied <= count, "bad batch");
        require(batchOfRoot[root] == 0, "already sealed");
        id = ++batchCount;
        batches[id] = Batch({
            rulesetId: rulesetId, count: count, denied: denied, sealedAt: uint64(block.timestamp), root: root
        });
        batchOfRoot[root] = id;
        Stats storage s = stats[rulesetId];
        s.batches += 1;
        s.decisions += count;
        s.denied += denied;
        emit BatchSealed(id, rulesetId, root, count, denied);
    }

    function leafOf(uint8 outcome, bytes32 receiptHash) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(outcome, receiptHash));
    }

    /// @notice True if this receipt, with this outcome, is in this batch.
    function verify(uint32 batchId, uint8 outcome, bytes32 receiptHash, bytes32[] calldata proof)
        public
        view
        returns (bool)
    {
        bytes32 root = batches[batchId].root;
        if (root == bytes32(0)) return false;
        return _rootOf(leafOf(outcome, receiptHash), proof) == root;
    }

    /// @notice File an appeal against a sealed denial. Anyone holding the receipt can file,
    /// so a legal-aid worker can file for someone without a wallet.
    function fileAppeal(uint32 batchId, bytes32 receiptHash, bytes32[] calldata proof, bytes32 groundsHash)
        external
        returns (uint32 id)
    {
        require(verify(batchId, DENIED, receiptHash, proof), "not a sealed denial");
        require(groundsHash != bytes32(0), "empty grounds");
        bytes32 leaf = leafOf(DENIED, receiptHash);
        require(appealOfLeaf[leaf] == 0, "already appealed");
        id = ++appealCount;
        appeals[id] = Appeal({
            batchId: batchId,
            status: OPEN,
            filedAt: uint64(block.timestamp),
            answeredAt: 0,
            filer: msg.sender,
            leaf: leaf,
            groundsHash: groundsHash,
            answerHash: bytes32(0)
        });
        appealOfLeaf[leaf] = id;
        stats[batches[batchId].rulesetId].appeals += 1;
        emit AppealFiled(id, batchId, leaf, msg.sender, groundsHash);
    }

    /// @notice The agency answers an appeal: the decision stands, or it is overturned.
    function answerAppeal(uint32 id, bool overturned, bytes32 answerHash) external {
        Appeal storage a = appeals[id];
        require(a.filedAt != 0, "no such appeal");
        require(a.status == OPEN, "already answered");
        uint32 rulesetId = batches[a.batchId].rulesetId;
        require(rulesets[rulesetId].agency == msg.sender, "not the agency");
        require(answerHash != bytes32(0), "empty answer");
        a.status = overturned ? OVERTURNED : UPHELD;
        a.answeredAt = uint64(block.timestamp);
        a.answerHash = answerHash;
        Stats storage s = stats[rulesetId];
        if (overturned) s.overturned += 1;
        else s.upheld += 1;
        emit AppealAnswered(id, a.status, answerHash);
    }

    /// @notice An open appeal past the response time the agency committed to.
    function isOverdue(uint32 id) external view returns (bool) {
        Appeal storage a = appeals[id];
        if (a.filedAt == 0 || a.status != OPEN) return false;
        uint64 days_ = rulesets[batches[a.batchId].rulesetId].responseDays;
        return block.timestamp > a.filedAt + days_ * 1 days;
    }

    /// Sorted-pair Merkle root, the same scheme as OpenZeppelin's MerkleProof.
    function _rootOf(bytes32 leaf, bytes32[] calldata proof) internal pure returns (bytes32 h) {
        h = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            h = h < p ? keccak256(abi.encodePacked(h, p)) : keccak256(abi.encodePacked(p, h));
        }
    }
}
