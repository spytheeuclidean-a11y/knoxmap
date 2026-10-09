use knoxlots::cell::{Cell, Square};
use knoxlots::compile::{compile_cell, Manifest};
use knoxlots::header::{Header, Room};
use knoxlots::kcell::KCell;
use knoxlots::pack::Pack;

fn sample() -> KCell {
    let mut c = Cell::empty(2);
    let grass = c.name_index("blends_natural_01_0");
    let wall = c.name_index("walls_exterior_house_01_0");
    let floor = c.name_index("floors_interior_tilesandwood_01_0");
    for x in 0..256 {
        for y in 0..256 {
            c.set(0, x, y, Some(Square { room: 0xFFFF_FFFF, tiles: vec![grass] }));
        }
    }
    c.set(0, 10, 20, Some(Square { room: 0, tiles: vec![floor, wall] }));
    c.set(1, 255, 255, Some(Square { room: 0xFFFF_FFFF, tiles: vec![wall] }));
    KCell {
        cell_x: 83,
        cell_y: 2,
        min_z: 0,
        rooms: vec![Room { name: "bedroom".into(), z: 0, rects: vec![[10, 20, 1, 1]], objects: vec![[4, 1, 2]] }],
        buildings: vec![vec![0]],
        zombie: None,
        squares: c,
    }
}

#[test]
fn source_round_trips() {
    let k = sample();
    let bytes = k.write().unwrap();
    let back = KCell::parse(&bytes).unwrap();
    assert_eq!(back, k);
    assert_eq!(back.write().unwrap(), bytes);
    let mut with_zombie = k.clone();
    with_zombie.zombie = Some(vec![3; 1024]);
    assert_eq!(KCell::parse(&with_zombie.write().unwrap()).unwrap(), with_zombie);
}

#[test]
fn compiled_files_read_back_as_the_same_cell() {
    let k = sample();
    let files = compile_cell(&k, &Manifest::default(), None);
    let h = Header::parse(&files.header).unwrap();
    let p = Pack::parse(&files.pack).unwrap();
    // The table holds the used tiles once each, sorted by name.
    assert_eq!(h.tiles, vec!["blends_natural_01_0", "floors_interior_tilesandwood_01_0", "walls_exterior_house_01_0"]);
    assert_eq!((h.min_z, h.max_z), (0, 1));
    let cell = Cell::from_pack(&h.tiles, &p, 2).unwrap();
    let sq = cell.get(0, 10, 20).unwrap();
    assert_eq!(sq.room, 0);
    assert_eq!(sq.tiles.iter().map(|&t| cell.names[t as usize].as_str()).collect::<Vec<_>>(),
               ["floors_interior_tilesandwood_01_0", "walls_exterior_house_01_0"]);
    assert!(cell.get(1, 255, 255).is_some() && cell.get(1, 0, 0).is_none());
    // No spawn map and no stored bytes: no zombies.
    assert!(h.chunk_values.iter().all(|&b| b == 0));
    assert_eq!(files.chunkdata.len(), 1026);
}

#[test]
fn damaged_sources_are_errors_not_panics() {
    let bytes = sample().write().unwrap();
    for len in (0..bytes.len()).step_by(997) {
        let _ = KCell::parse(&bytes[..len]);
    }
    let mut bad = bytes.clone();
    bad[4..8].copy_from_slice(&9u32.to_le_bytes());
    assert!(KCell::parse(&bad).is_err(), "unknown version");
    assert!(KCell::parse(b"KCEL").is_err());
    let mut over = bytes.clone();
    over.extend_from_slice(&[1, 2, 3]);
    assert!(KCell::parse(&over).is_err(), "bytes after the squares");
    let mut huge_levels = bytes;
    huge_levels[20..24].copy_from_slice(&u32::MAX.to_le_bytes());
    assert!(KCell::parse(&huge_levels).is_err());
}

#[test]
fn manifest_is_checked() {
    let m = Manifest::parse("format = knoxlots-source 1\norigin_x = 21000 # west edge\nspawn_map = z.bmp\n").unwrap();
    assert_eq!((m.origin_x, m.spawn_map.as_deref(), m.field_a), (21000, Some("z.bmp"), 8));
    assert_eq!(Manifest::parse(&m.write()).unwrap(), m);
    assert!(Manifest::parse("origin_x = 8\n").is_err(), "no format line");
    assert!(Manifest::parse("format = knoxlots-source 1\norigin_x = 5\n").is_err(), "not a chunk multiple");
    assert!(Manifest::parse("format = knoxlots-source 1\nbogus = 1\n").is_err(), "unknown setting");
    assert!(Manifest::parse("format = knoxlots-source 2\n").is_err(), "unknown format");
}
