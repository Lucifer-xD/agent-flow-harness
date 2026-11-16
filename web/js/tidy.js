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
