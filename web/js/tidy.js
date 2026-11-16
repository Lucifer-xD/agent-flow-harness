// Commands and their output, as people read them.

/** A command's output with its progress redraws folded: a line rewritten with carriage returns keeps its last
 *  state, and a run of lines that differ only in their numbers or bar (a download counting up) keeps the newest. */
export function tidyOutput(text) {
  if (!text) return "";
  const lines = [];
  let prev = null;
  for (let raw of String(text).split("\n")) {
    if (raw.includes("\r")) {
      const parts = raw.split("\r").filter((x) => x.trim());
      raw = parts.length ? parts[parts.length - 1] : "";
    }
    const progress = /\d\s*%|[▀-▟#=]{3,}|\b\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?\b|\bETA\b|\b\d+(?:\.\d+)?\s*[kKMG]i?B\/s/.test(raw);
    const key = progress ? raw.replace(/[▀-▟#=>\-\s]+/g, " ").replace(/\d+(?:\.\d+)?/g, "0").trim() : null;
    if (key && key === prev) lines[lines.length - 1] = raw;
    else lines.push(raw);
    prev = key;
  }
  return lines.join("\n");
}

/** The part of a command worth reading in one line: what runs, without the wrapper it runs through
 *  (`ssh -o ... user@host "..."`, `bash -lc "..."`, `powershell -Command "..."`, `cmd /c ...`).
 *  `via` names the wrapper ("ssh", "powershell") when there was one. */
export function shortCommand(cmd) {
  let s = String(cmd || "").trim(), via = "", m;
  const sshOpts = "((?:-[A-Za-z]\\s*\\S+\\s+|-[A-Za-z]+\\s+)*)";
  if ((m = s.match(new RegExp("^ssh\\s+" + sshOpts + "(\\S+)\\s+([\"'])([\\s\\S]*)\\3\\s*$")))) { via = "ssh"; s = m[4]; }
  else if ((m = s.match(new RegExp("^ssh\\s+" + sshOpts + "(\\S+@\\S+)\\s+(\\S[\\s\\S]*)$")))) { via = "ssh"; s = m[3]; }
  else if ((m = s.match(/^(?:bash|sh|zsh)\s+-l?c\s+(["'])([\s\S]*)\1\s*$/))) s = m[2];
  else if ((m = s.match(/^(?:powershell|pwsh)(?:\.exe)?\s+(?:-NoProfile\s+)?(?:-Command\s+)?(["'])([\s\S]*)\1\s*$/i))) { via = "powershell"; s = m[2]; }
  else if ((m = s.match(/^cmd(?:\.exe)?\s+\/c\s+([\s\S]*)$/i))) s = m[1].replace(/^"([\s\S]*)"$/, "$1");
  return { text: s.replace(/\s+/g, " ").trim(), via };
}

/** Which program a command runs, as the name of an icon: a file-type icon ("python", "npm", "git", "docker"…)
 *  or one of the app's own icons ("app:globe" for curl, "app:search" for grep). null when nothing fits.
 *  Wrappers are looked through (ssh, bash -lc, sudo, env assignments, "cd x &&"). */
const PROGRAMS = {
  python: "python", python3: "python", py: "python", pip: "python", pip3: "python", pytest: "python", uv: "python", uvx: "python", poetry: "python", conda: "python", ruff: "python", mypy: "python", black: "python",
  jupyter: "jupyter", node: "nodejs", nodejs: "nodejs", deno: "nodejs", bun: "nodejs", bunx: "nodejs", nvm: "nodejs", tsx: "typescript", tsc: "typescript", "ts-node": "typescript",
  npm: "npm", npx: "npm", pnpm: "npm", yarn: "npm", git: "git", gh: "git", docker: "docker", "docker-compose": "docker", podman: "docker",
  go: "go", cargo: "rust", rustc: "rust", rustup: "rust", java: "java", javac: "java", mvn: "java", gradle: "java", gradlew: "java", kotlin: "kotlin", kotlinc: "kotlin",
  dotnet: "csharp", csc: "csharp", php: "php", composer: "php", ruby: "ruby", gem: "ruby", bundle: "ruby", rails: "ruby", rake: "ruby",
  powershell: "powershell", pwsh: "powershell", bash: "console", sh: "console", zsh: "console", cmd: "console", echo: "console",
  gcc: "c", cc: "c", clang: "c", make: "c", cmake: "c", "g++": "cpp", "clang++": "cpp", swift: "swift", dart: "dart", flutter: "dart", lua: "lua", perl: "perl",
  rscript: "r", julia: "julia", elixir: "elixir", mix: "elixir", zig: "zig", scala: "scala", sbt: "scala", ghc: "haskell", cabal: "haskell", stack: "haskell", vim: "vim", nvim: "vim",
  sqlite3: "database", psql: "database", mysql: "database", mongosh: "database", "redis-cli": "database", prisma: "prisma",
  tar: "zip", zip: "zip", unzip: "zip", "7z": "zip", gzip: "zip", openssl: "certificate", "ssh-keygen": "key", gpg: "key",
  cat: "document", type: "document", head: "document", tail: "document", less: "document", more: "document", wc: "document",
  ls: "folder", dir: "folder", cd: "folder", pwd: "folder", tree: "folder", mkdir: "folder", cp: "folder", mv: "folder", copy: "folder", move: "folder", xcopy: "folder", robocopy: "folder", du: "folder", df: "folder",
  curl: "app:globe", wget: "app:globe", "invoke-webrequest": "app:globe", ping: "app:globe", ssh: "app:monitor", scp: "app:monitor", rsync: "app:monitor",
  grep: "app:search", rg: "app:search", findstr: "app:search", find: "app:search", "select-string": "app:search", rm: "app:trash", del: "app:trash", rmdir: "app:trash",
  systemctl: "settings", service: "settings", chmod: "lock", chown: "lock", sudo: "lock", kill: "app:stop", pkill: "app:stop", taskkill: "app:stop",
};
const SKIP = new Set(["cd", "set", "export", "source", "sudo", "env", "time", "nohup", "call", "exec", "command"]);
const WEAK = new Set(["folder", "document", "console", "lock", "settings", "app:search", "app:trash", "app:stop"]); // everyday commands: a real program beside them wins
export function commandKind(cmd) {
  const { text, via } = shortCommand(cmd);
  let weak = null;
  for (const part of text.split(/&&|\|\||;|\|/)) {
    const seg = part.trim(), quoted = seg.match(/^(["'])(.+?)\1/); // a program given as a quoted path, spaces and all
    const words = quoted ? [quoted[2].replace(/\s+/g, "_")] : seg.split(/\s+/).filter((w) => w && !/^[A-Za-z_][A-Za-z0-9_]*=/.test(w)); // FOO=1 before the program
    while (words.length > 1 && SKIP.has(words[0].toLowerCase())) words.shift();
    let w = (words[0] || "").replace(/^["'(&\s]+|["')]+$/g, "");
    if (!w) continue;
    w = w.split(/[\\/]/).pop().toLowerCase().replace(/\.(exe|cmd|bat|ps1|sh)$/, "");
    const k = PROGRAMS[w] || (/^python[\d.]*$/.test(w) || /^pip[\d.]*$/.test(w) ? "python" : /^node\d*$/.test(w) ? "nodejs"
      : /^(get-childitem|set-location|new-item|copy-item|move-item|test-path)$/.test(w) ? "folder" : /^get-content$/.test(w) ? "document" : /^remove-item$/.test(w) ? "app:trash"
        : /^[a-z]+-[a-z]+$/.test(w) && via === "powershell" ? "powershell" : null);
    if (k && !WEAK.has(k)) return k;
    weak ??= k;
  }
  return weak || (via === "powershell" ? "powershell" : via === "ssh" ? "app:monitor" : via ? "console" : null);
}
