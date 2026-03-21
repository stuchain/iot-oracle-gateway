const fs = require("fs/promises");
const path = require("path");
const hre = require("hardhat");

async function main() {
  const TelemetryAnchor = await hre.ethers.getContractFactory("TelemetryAnchor");
  const anchor = await TelemetryAnchor.deploy();
  await anchor.waitForDeployment();
  const address = await anchor.getAddress();
  console.log("TelemetryAnchor deployed to:", address);

  const deploymentsDir = path.join(__dirname, "..", "deployments");
  await fs.mkdir(deploymentsDir, { recursive: true });
  const outPath = path.join(deploymentsDir, "localhost.json");

  const chainId =
    hre.network.config.chainId !== undefined
      ? Number(hre.network.config.chainId)
      : 31337;

  const payload = {
    network: hre.network.name,
    rpcUrl: hre.network.config.url ?? "http://127.0.0.1:8545",
    chainId,
    contractAddress: address,
  };
  await fs.writeFile(outPath, JSON.stringify(payload, null, 2) + "\n", "utf8");
  console.log("Wrote deployment record to:", outPath);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
