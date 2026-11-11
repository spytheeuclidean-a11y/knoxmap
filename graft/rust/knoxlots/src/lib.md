# rust/knoxlots/src/lib.rs

- bmp · module · L10-L10 — pub mod bmp;
- cell · module · L11-L11 — pub mod cell;
- chunkdata · module · L12-L12 — pub mod chunkdata;
- compile · module · L13-L13 — pub mod compile;
- header · module · L14-L14 — pub mod header;
- kcell · module · L15-L15 — pub mod kcell;
- pack · module · L16-L16 — pub mod pack;
- spawn · module · L17-L17 — pub mod spawn;
- Reader · struct · L20-L23 — pub struct Reader<'a>
- new · function · L26-L28 — pub fn new(data: &'a [u8]) -> Self
- left · function · L30-L32 — pub fn left(&self) -> usize
- bytes · function · L34-L41 — pub fn bytes(&mut self, n: usize) -> Result<&'a [u8], String>
- u32 · function · L43-L46 — pub fn u32(&mut self) -> Result<u32, String>
- u64 · function · L48-L53 — pub fn u64(&mut self) -> Result<u64, String>
- line · function · L56-L62 — pub fn line(&mut self) -> Result<String, String>
- put_u32 · function · L65-L67 — pub(crate) fn put_u32(out: &mut Vec<u8>, v: u32)
