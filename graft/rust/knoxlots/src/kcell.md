# rust/knoxlots/src/kcell.rs

- MAGIC · constant · L27-L27 — pub const MAGIC: &[u8; 4] = b"KCEL";
- NONE · constant · L28-L28 — const NONE: u32 = 0xFFFF_FFFF;
- KCell · struct · L31-L39 — pub struct KCell
- put_str · function · L41-L46 — fn put_str(o: &mut Vec<u8>, s: &str) -> Result<(), String>
- get_str · function · L48-L52 — fn get_str(r: &mut Reader) -> Result<String, String>
- write · function · L55-L113 — pub fn write(&self) -> Result<Vec<u8>, String>
- parse · function · L115-L204 — pub fn parse(data: &[u8]) -> Result<KCell, String>
