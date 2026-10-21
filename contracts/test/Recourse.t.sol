// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {Recourse} from "../src/Recourse.sol";

contract RecourseTest is Test {
    Recourse r;
    address agency = makeAddr("agency");
    address other = makeAddr("other agency");
    address legalAid = makeAddr("legal aid");

    bytes32 constant RULES = keccak256("rules v1");

    // From test/fixtures/batch.json, written by engine/make_fixture.py.
    bytes32 root;
    uint8[] outcomes;
    bytes32[] hashes;
    bytes32[][] proofs;

    function setUp() public {
        r = new Recourse();
        string memory json = vm.readFile("test/fixtures/batch.json");
        root = vm.parseJsonBytes32(json, ".root");
        for (uint256 i = 0; i < 7; i++) {
            string memory p = string.concat(".items[", vm.toString(i), "]");
            outcomes.push(uint8(vm.parseJsonUint(json, string.concat(p, ".outcome"))));
            hashes.push(vm.parseJsonBytes32(json, string.concat(p, ".receiptHash")));
            proofs.push(vm.parseJsonBytes32Array(json, string.concat(p, ".proof")));
        }
        vm.prank(agency);
        r.nameAgency("Civil Supplies Department (demo)");
    }

    function _publish() internal returns (uint32 id) {
        vm.prank(agency);
        id = r.publishRuleset(RULES, "https://example.org/rules/v1.json", 30);
        vm.roll(block.number + 1);
    }

    function _seal() internal returns (uint32 rid, uint32 bid) {
        rid = _publish();
        vm.prank(agency);
        bid = r.sealBatch(rid, root, 7, 3);
    }

    function _denied() internal view returns (uint256 i) {
        for (i = 0; i < outcomes.length; i++) {
            if (outcomes[i] == r.DENIED()) return i;
        }
        revert("fixture has no denial");
    }

    function _eligible() internal view returns (uint256 i) {
        for (i = 0; i < outcomes.length; i++) {
            if (outcomes[i] == r.ELIGIBLE()) return i;
        }
        revert("fixture has no eligible");
    }

    // --- agencies and rulesets

    function test_agencyNamesItselfOnce() public {
        vm.prank(agency);
        vm.expectRevert("already named");
        r.nameAgency("Someone else");
        assertEq(r.agencyName(agency), "Civil Supplies Department (demo)");
    }

    function test_unnamedAgencyCannotPublish() public {
        vm.prank(other);
        vm.expectRevert("name the agency first");
        r.publishRuleset(RULES, "x", 30);
    }

    function test_publishRecordsTheRuleset() public {
        uint32 id = _publish();
        (address a, uint64 at, uint64 blk, uint64 retired, uint16 days_, bytes32 h, string memory uri) =
            r.rulesets(id);
        assertEq(a, agency);
        assertEq(at, block.timestamp);
        assertEq(blk, block.number - 1);
        assertEq(retired, 0);
        assertEq(days_, 30);
        assertEq(h, RULES);
        assertEq(uri, "https://example.org/rules/v1.json");
        assertEq(r.rulesetOfHash(agency, RULES), id);
    }

    function test_sameRulesCannotBePublishedTwice() public {
        _publish();
        vm.prank(agency);
        vm.expectRevert("already published");
        r.publishRuleset(RULES, "again", 30);
    }

    function test_responseDaysMustBeSet() public {
        vm.prank(agency);
        vm.expectRevert("bad response days");
        r.publishRuleset(RULES, "x", 0);
    }

    // --- sealing

    function test_rulesMustBePublicBeforeTheyAreUsed() public {
        vm.startPrank(agency);
        uint32 id = r.publishRuleset(RULES, "x", 30);
        vm.expectRevert("publish the rules first");
        r.sealBatch(id, root, 7, 3); // same block
        vm.roll(block.number + 1);
        r.sealBatch(id, root, 7, 3);
        vm.stopPrank();
    }

    function test_onlyTheAgencyCanSealUnderItsRules() public {
        uint32 id = _publish();
        vm.prank(other);
        vm.expectRevert("not the agency");
        r.sealBatch(id, root, 7, 3);
    }

    function test_sealCountsTowardTheRuleset() public {
        (uint32 rid, uint32 bid) = _seal();
        (uint32 rs, uint32 count, uint32 denied, uint64 at, bytes32 rt) = r.batches(bid);
        assertEq(rs, rid);
        assertEq(count, 7);
        assertEq(denied, 3);
        assertEq(at, block.timestamp);
        assertEq(rt, root);
        (uint32 batches, uint32 decisions, uint32 deniedTotal,,,) = r.stats(rid);
        assertEq(batches, 1);
        assertEq(decisions, 7);
        assertEq(deniedTotal, 3);
    }

    function test_aRootIsSealedOnce() public {
        (uint32 rid,) = _seal();
        vm.prank(agency);
        vm.expectRevert("already sealed");
        r.sealBatch(rid, root, 7, 3);
    }

    function test_badBatchesAreRefused() public {
        uint32 id = _publish();
        vm.startPrank(agency);
        vm.expectRevert("bad batch");
        r.sealBatch(id, root, 7, 8);
        vm.expectRevert("bad batch");
        r.sealBatch(id, root, 0, 0);
        vm.expectRevert("bad batch");
        r.sealBatch(id, bytes32(0), 7, 3);
        vm.stopPrank();
    }

    function test_retiredRulesCannotBeUsed() public {
        uint32 id = _publish();
        vm.startPrank(agency);
        r.retireRuleset(id);
        vm.expectRevert("ruleset retired");
        r.sealBatch(id, root, 7, 3);
        vm.stopPrank();
    }

    // --- receipts

    function test_everyEngineReceiptVerifies() public {
        (, uint32 bid) = _seal();
        for (uint256 i = 0; i < hashes.length; i++) {
            assertTrue(r.verify(bid, outcomes[i], hashes[i], proofs[i]));
        }
    }

    function test_aReceiptWithTheWrongOutcomeFails() public {
        (, uint32 bid) = _seal();
        uint256 i = _denied();
        assertFalse(r.verify(bid, r.ELIGIBLE(), hashes[i], proofs[i]));
    }

    function test_anEditedReceiptFails() public {
        (, uint32 bid) = _seal();
        uint256 i = _denied();
        assertFalse(r.verify(bid, outcomes[i], keccak256(abi.encode(hashes[i])), proofs[i]));
        assertFalse(r.verify(bid + 1, outcomes[i], hashes[i], proofs[i]));
    }

    // --- appeals

    function test_appealAgainstADenial() public {
        (uint32 rid, uint32 bid) = _seal();
        uint256 i = _denied();
        vm.prank(legalAid);
        uint32 id = r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
        (uint32 b, uint8 status, uint64 filed,, address filer, bytes32 leaf, bytes32 grounds,) = r.appeals(id);
        assertEq(b, bid);
        assertEq(status, r.OPEN());
        assertEq(filed, block.timestamp);
        assertEq(filer, legalAid);
        assertEq(leaf, r.leafOf(r.DENIED(), hashes[i]));
        assertEq(grounds, keccak256("letter"));
        (,,, uint32 appeals,,) = r.stats(rid);
        assertEq(appeals, 1);
    }

    function test_cannotAppealAnEligibleDecision() public {
        (, uint32 bid) = _seal();
        uint256 i = _eligible();
        vm.expectRevert("not a sealed denial");
        r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
    }

    function test_oneAppealPerDecision() public {
        (, uint32 bid) = _seal();
        uint256 i = _denied();
        r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
        vm.expectRevert("already appealed");
        r.fileAppeal(bid, hashes[i], proofs[i], keccak256("another letter"));
    }

    function test_onlyTheAgencyAnswersAndOnlyOnce() public {
        (uint32 rid, uint32 bid) = _seal();
        uint256 i = _denied();
        uint32 id = r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
        vm.prank(other);
        vm.expectRevert("not the agency");
        r.answerAppeal(id, true, keccak256("answer"));
        vm.prank(agency);
        r.answerAppeal(id, true, keccak256("answer"));
        vm.prank(agency);
        vm.expectRevert("already answered");
        r.answerAppeal(id, false, keccak256("changed my mind"));
        (, uint8 status,, uint64 answered,,,, bytes32 answer) = r.appeals(id);
        assertEq(status, r.OVERTURNED());
        assertEq(answered, block.timestamp);
        assertEq(answer, keccak256("answer"));
        (,,,, uint32 upheld, uint32 overturned) = r.stats(rid);
        assertEq(upheld, 0);
        assertEq(overturned, 1);
    }

    function test_upheldAppealsAreCountedToo() public {
        (uint32 rid, uint32 bid) = _seal();
        uint256 i = _denied();
        uint32 id = r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
        vm.prank(agency);
        r.answerAppeal(id, false, keccak256("the car is yours"));
        (,,,, uint32 upheld, uint32 overturned) = r.stats(rid);
        assertEq(upheld, 1);
        assertEq(overturned, 0);
    }

    function test_anUnansweredAppealGoesOverdue() public {
        (, uint32 bid) = _seal();
        uint256 i = _denied();
        uint32 id = r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
        vm.warp(block.timestamp + 30 days);
        assertFalse(r.isOverdue(id));
        vm.warp(block.timestamp + 1);
        assertTrue(r.isOverdue(id));
        vm.prank(agency);
        r.answerAppeal(id, true, keccak256("late, but overturned"));
        assertFalse(r.isOverdue(id));
    }

    function test_retiringRulesKeepsAppealsOpen() public {
        (uint32 rid, uint32 bid) = _seal();
        uint256 i = _denied();
        uint32 id = r.fileAppeal(bid, hashes[i], proofs[i], keccak256("letter"));
        vm.startPrank(agency);
        r.retireRuleset(rid);
        r.answerAppeal(id, true, keccak256("answer"));
        vm.stopPrank();
    }
}
