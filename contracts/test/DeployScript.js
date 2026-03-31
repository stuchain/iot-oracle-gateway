const { expect } = require("chai");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

describe("deploy.js", function () {
  it("writes deployment record with expected fields", function () {
    const contractsRoot = path.join(__dirname, "..");
    const outPath = path.join(contractsRoot, "deployments", "localhost.json");

    if (fs.existsSync(outPath)) {
      fs.unlinkSync(outPath);
    }

    execSync("npx hardhat run scripts/deploy.js", {
      cwd: contractsRoot,
      stdio: "pipe",
      windowsHide: true,
    });

    expect(fs.existsSync(outPath)).to.equal(true);
    const raw = fs.readFileSync(outPath, "utf8");
    expect(raw.endsWith("\n")).to.equal(true);
    const payload = JSON.parse(raw);

    expect(payload).to.have.keys("network", "rpcUrl", "chainId", "contractAddress");
    expect(payload.network).to.be.a("string");
    expect(payload.rpcUrl).to.be.a("string");
    expect(payload.chainId).to.be.a("number");
    expect(payload.contractAddress).to.match(/^0x[a-fA-F0-9]{40}$/);
  });
});
