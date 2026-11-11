# rust/knoxlots/src/bin/knoxlots.rs

- Tally · struct · L22-L26 — struct Tally
- note · function · L29-L36 — fn note(&mut self, name: &str, ok: Result<bool, String>)
- files · function · L39-L47 — fn files(dir: &str) -> Result<Vec<PathBuf>, String>
- name_of · function · L49-L51 — fn name_of(p: &Path) -> String
- rebuild · function · L54-L63 — fn rebuild(head_bytes: &[u8], pack_bytes: &[u8]) -> Result<(bool, bool), String>
- verify · function · L65-L120 — fn verify(dir: &str, deep: bool) -> ExitCode
- blank · function · L122-L153 — fn blank(input: &str, output: &str) -> ExitCode
- cell_of · function · L155-L159 — fn cell_of(name: &str, prefix: &str, suffix: &str) -> Option<(u32, u32)>
- export · function · L161-L202 — fn export(lots: &str, src: &str, keep_zombie: bool) -> ExitCode
- compile · function · L204-L282 — fn compile(src: &str, out: &str, threads: usize) -> ExitCode
- compare · function · L284-L309 — fn compare(a: &str, b: &str) -> ExitCode
- main · function · L311-L330 — fn main() -> ExitCode
