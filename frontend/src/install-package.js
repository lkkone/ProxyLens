import macInstall from "./installers/install-mac.command?raw";
import macUninstall from "./installers/uninstall-mac.command?raw";
import linuxInstall from "./installers/install-linux.sh?raw";
import linuxUninstall from "./installers/uninstall-linux.sh?raw";
import windowsInstall from "./installers/install-windows.ps1?raw";
import windowsUninstall from "./installers/uninstall-windows.ps1?raw";

const encoder = new TextEncoder();
const crcTable = Array.from({ length: 256 }, (_, i) => {
  for (let bit = 0; bit < 8; bit++) i = (i >>> 1) ^ (i & 1 ? 0xedb88320 : 0);
  return i >>> 0;
});
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = (crc >>> 8) ^ crcTable[(crc ^ byte) & 255];
  return (crc ^ 0xffffffff) >>> 0;
}
// Uncompressed ZIP keeps packaging local: controller secrets never leave the browser.
export function zipFiles(files) {
  const local = [],
    central = [];
  let offset = 0,
    centralSize = 0;
  for (const file of files) {
    const name = encoder.encode(file.name);
    const bytes =
      typeof file.data === "string" ? encoder.encode(file.data) : file.data;
    const crc = crc32(bytes);
    const header = new Uint8Array(30 + name.length);
    const h = new DataView(header.buffer);
    h.setUint32(0, 0x04034b50, true);
    h.setUint16(4, 20, true);
    h.setUint16(6, 0x800, true);
    h.setUint16(12, 0x21, true);
    h.setUint32(14, crc, true);
    h.setUint32(18, bytes.length, true);
    h.setUint32(22, bytes.length, true);
    h.setUint16(26, name.length, true);
    header.set(name, 30);
    local.push(header, bytes);
    const entry = new Uint8Array(46 + name.length);
    const e = new DataView(entry.buffer);
    e.setUint32(0, 0x02014b50, true);
    e.setUint16(4, 0x314, true);
    e.setUint16(6, 20, true);
    e.setUint16(8, 0x800, true);
    e.setUint16(14, 0x21, true);
    e.setUint32(16, crc, true);
    e.setUint32(20, bytes.length, true);
    e.setUint32(24, bytes.length, true);
    e.setUint16(28, name.length, true);
    e.setUint32(38, (file.executable ? 0o100700 : 0o100600) * 65536, true);
    e.setUint32(42, offset, true);
    entry.set(name, 46);
    central.push(entry);
    centralSize += entry.length;
    offset += header.length + bytes.length;
  }
  const footer = new Uint8Array(22),
    f = new DataView(footer.buffer);
  f.setUint32(0, 0x06054b50, true);
  f.setUint16(8, files.length, true);
  f.setUint16(10, files.length, true);
  f.setUint32(12, centralSize, true);
  f.setUint32(16, offset, true);
  return new Blob([...local, ...central, footer], { type: "application/zip" });
}
export function installFiles(target, config, bytes) {
  const windows = target.startsWith("windows"),
    mac = target.startsWith("darwin");
  const prefix = `proxylens-${target}/`;
  const files = [
    {
      name: windows ? "proxylens-agent.exe" : "proxylens-agent",
      data: bytes,
      executable: true,
    },
    { name: "agent.json", data: JSON.stringify(config, null, 2) + "\n" },
  ];
  if (windows) {
    files.push(
      { name: "install.ps1", data: "\ufeff" + windowsInstall },
      { name: "uninstall.ps1", data: "\ufeff" + windowsUninstall },
    );
    for (const action of ["install", "uninstall"])
      files.push({
        name: `${action}.cmd`,
        data: `@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0${action}.ps1"\r\nset "INSTALL_RESULT=%ERRORLEVEL%"\r\npause\r\nexit /b %INSTALL_RESULT%\r\n`,
      });
  } else {
    files.push(
      {
        name: mac ? "install.command" : "install.sh",
        data: mac ? macInstall : linuxInstall,
        executable: true,
      },
      {
        name: mac ? "uninstall.command" : "uninstall.sh",
        data: mac ? macUninstall : linuxUninstall,
        executable: true,
      },
    );
  }
  return files.map((file) => ({ ...file, name: prefix + file.name }));
}
