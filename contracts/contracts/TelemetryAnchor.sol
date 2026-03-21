// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TelemetryAnchor {
    struct AnchorRecord {
        bytes32 batchHash;
        uint256 startMs;
        uint256 endMs;
        uint256 count;
        address submitter;
    }

    AnchorRecord[] public anchors;

    event Anchored(
        bytes32 batchHash,
        uint256 startMs,
        uint256 endMs,
        uint256 count,
        address submitter
    );

    function anchor(
        bytes32 batchHash,
        uint256 startMs,
        uint256 endMs,
        uint256 count
    ) public {
        anchors.push(
            AnchorRecord({
                batchHash: batchHash,
                startMs: startMs,
                endMs: endMs,
                count: count,
                submitter: msg.sender
            })
        );
        emit Anchored(batchHash, startMs, endMs, count, msg.sender);
    }

    function anchorCount() external view returns (uint256) {
        return anchors.length;
    }
}
