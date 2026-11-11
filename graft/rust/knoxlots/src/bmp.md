# rust/knoxlots/src/bmp.rs

- GreyImage · struct · L7-L11 — pub struct GreyImage
- view · function · L14-L16 — pub fn view(&self) -> Grey<'_>
- le16 · function · L19-L21 — fn le16(d: &[u8], o: usize) -> Result<u16, String>
- le32 · function · L23-L25 — fn le32(d: &[u8], o: usize) -> Result<u32, String>
- read_grey · function · L27-L75 — pub fn read_grey(d: &[u8]) -> Result<GreyImage, String>
- grey · function · L78-L84 — fn grey(r: u8, g: u8, b: u8) -> u8
