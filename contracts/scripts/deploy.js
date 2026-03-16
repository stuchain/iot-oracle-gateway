// Stub; real deploy script in Phase 5.
const hre = require("hardhat");

async function main() {
  const TelemetryAnchor = await hre.ethers.getContractFactory("TelemetryAnchor");
  const anchor = await TelemetryAnchor.deploy();
  await anchor.waitForDeployment();
  const address = await anchor.getAddress();
  console.log("TelemetryAnchor deployed to:", address);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
