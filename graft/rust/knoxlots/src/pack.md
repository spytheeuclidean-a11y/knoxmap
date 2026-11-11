# rust/knoxlots/src/pack.rs

- MAGIC · constant · L16-L16 — pub const MAGIC: &[u8; 4] = b"LOTP";
- SQUARES_PER_LEVEL · constant · L17-L17 — pub const SQUARES_PER_LEVEL: usize = 64;
- SKIP · constant · L18-L18 — const SKIP: u32 = 0xFFFF_FFFF;
- Rec · enum · L21-L25 — pub enum Rec
- Pack · struct · L28-L31 — pub struct Pack
- parse_chunk · function · L33-L53 — fn parse_chunk(bytes: &[u8]) -> Result<Vec<Rec>, String>
- write_chunk · function · L55-L68 — fn write_chunk(recs: &[Rec], out: &mut Vec<u8>)
- parse · function · L71-L92 — pub fn parse(data: &[u8]) -> Result<Pack, String>
- write · function · L94-L111 — pub fn write(&self) -> Vec<u8>
- expand · function · L115-L124 — pub fn expand(recs: &[Rec]) -> Vec<Option<Vec<u32>>>
- encode · function · L127-L146 — pub fn encode(grid: &[Option<Vec<u32>>]) -> Vec<Rec>
