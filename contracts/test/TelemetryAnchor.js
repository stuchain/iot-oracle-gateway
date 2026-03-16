// Placeholder test: deploy and assert address is non-zero. Real behavior in Phase 5.
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
});
