# rust/knoxlots/src/spawn.rs

- CHUNK · constant · L12-L12 — pub const CHUNK: usize = 8;
- PIXEL · constant · L13-L13 — pub const PIXEL: usize = 10;
- CHUNKS_PER_SIDE · constant · L14-L14 — pub const CHUNKS_PER_SIDE: usize = 32;
- Grey · struct · L17-L21 — pub struct Grey<'a>
- at · function · L24-L33 — fn at(&self, tile_x: i64, tile_y: i64) -> u32
- chunk_intensity · function · L37-L45 — pub fn chunk_intensity(&self, chunk_x: i64, chunk_y: i64) -> u8
- index · function · L49-L51 — pub fn index(local_x: usize, local_y: usize) -> usize
- tests · module · L54-L70 — mod tests
- floors_the_mean_and_treats_outside_as_zero · function · L58-L69 — fn floors_the_mean_and_treats_outside_as_zero()
