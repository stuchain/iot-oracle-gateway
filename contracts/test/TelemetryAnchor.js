const { expect } = require("chai");
const hre = require("hardhat");

describe("TelemetryAnchor", function () {
  it("deploys with a non-zero address", async function () {
    const TelemetryAnchor = await hre.ethers.getContractFactory("TelemetryAnchor");
    const anchor = await TelemetryAnchor.deploy();
    await anchor.waitForDeployment();
    const address = await anchor.getAddress();
    expect(address).to.not.equal(hre.ethers.ZeroAddress);
    expect(address).to.match(/^0x[a-fA-F0-9]{40}$/);
  });

  it("anchor emits Anchored and appends AnchorRecord", async function () {
    const [signer] = await hre.ethers.getSigners();
    const TelemetryAnchor = await hre.ethers.getContractFactory("TelemetryAnchor");
    const anchor = await TelemetryAnchor.deploy();
    await anchor.waitForDeployment();

    const batchHash = hre.ethers.id("dummy-batch");
    const startMs = 1_000n;
    const endMs = 2_000n;
    const count = 7n;

    const tx = await anchor.connect(signer).anchor(batchHash, startMs, endMs, count);
    const receipt = await tx.wait();

    let anchored = null;
    for (const log of receipt.logs) {
      try {
        const parsed = anchor.interface.parseLog(log);
        if (parsed.name === "Anchored") {
          anchored = parsed;
          break;
        }
      } catch {
        // ignore non-matching logs
      }
    }
    expect(anchored).to.not.equal(null);
    expect(anchored.args.batchHash).to.equal(batchHash);
    expect(anchored.args.startMs).to.equal(startMs);
    expect(anchored.args.endMs).to.equal(endMs);
    expect(anchored.args.count).to.equal(count);
    expect(anchored.args.submitter).to.equal(signer.address);

    expect(await anchor.anchorCount()).to.equal(1n);

    const rec = await anchor.anchors(0);
    expect(rec.batchHash).to.equal(batchHash);
    expect(rec.startMs).to.equal(startMs);
    expect(rec.endMs).to.equal(endMs);
    expect(rec.count).to.equal(count);
    expect(rec.submitter).to.equal(signer.address);
  });
});
