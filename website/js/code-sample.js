// The login form the agent "writes" on the home page: the story's code card, the app's Live pane
// and the 3D code panel all type it out. Each part is [token kind, text]; kinds match .tok-* colours.
export const CODE = [
  ["k", "export function "], ["f", "LoginForm"], ["", "() {\n  "],
  ["k", "const "], ["", "[email, setEmail] = "], ["f", "useState"], ["", "("], ["s", '""'], ["", ");\n  "],
  ["k", "const "], ["", "[password, setPassword] = "], ["f", "useState"], ["", "("], ["s", '""'], ["", ");\n\n  "],
  ["k", "async function "], ["f", "submit"], ["", "(e) {\n    e."], ["f", "preventDefault"], ["", "();\n    "],
  ["k", "await "], ["f", "signIn"], ["", "({ email, password });\n    "], ["c", "// the server sets the session cookie\n    "],
  ["", "router."], ["f", "push"], ["", "("], ["s", '"/dashboard"'], ["", ");\n  }\n\n  "],
  ["k", "return "], ["", "(\n    <form onSubmit={submit}>\n      <Input label="], ["s", '"Email"'], ["", " value={email} />\n      <Input label="], ["s", '"Password"'], ["", " type="], ["s", '"password"'], ["", " />\n      <Button>Log in</Button>\n    </form>\n  );\n}"],
];

export const TOKEN_COLORS = { k: "#ff7ab6", s: "#ffc46b", f: "#ff9a5c", c: "#85796f", "": "#d9cdc3" };
