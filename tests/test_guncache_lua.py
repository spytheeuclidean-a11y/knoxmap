"""The guaranteed rifle handler must accept only real game containers."""
from pathlib import Path
import json
import tempfile
import unittest

try:
    from lupa import LuaRuntime
except ImportError:
    LuaRuntime = None

HANDLER = Path(__file__).resolve().parents[1] / 'knoxbuild' / 'lua' / 'guncache.lua'


class GunCache(unittest.TestCase):
    def test_game_type_check_precedes_get_parent(self):
        source = HANDLER.read_text(encoding='utf-8')
        self.assertLess(source.index('instanceof(container, "ItemContainer")'),
                        source.index('container:getParent()'))

    def test_map_install_copies_the_fixed_handler(self):
        from tools.make_map_mod import write_gun_cache
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'project').mkdir()
            (root / 'project' / 'town_guncache.json').write_text(json.dumps(
                {'x': 1, 'y': 2, 'w': 3, 'h': 4, 'items': ['Base.AssaultRifle']}))
            self.assertIsNotNone(write_gun_cache(str(root / 'project'), str(root / 'mod'), 'town'))
            shipped = root / 'mod/common/media/lua/server/KnoxMap/KnoxMapGunCache.lua'
            self.assertEqual(shipped.read_bytes(), HANDLER.read_bytes())

    @unittest.skipUnless(LuaRuntime, 'optional Lua test runtime not installed')
    def test_wrong_userdata_is_ignored_and_valid_container_receives_rifle_once(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
            Events = { OnFillContainer = { Add = function(f) handler = f end } }
            local saved = {}
            ModData = { getOrCreate = function(_) return saved end }
        ''')

        class WrongContainer:
            attempts = 0
            def __getattr__(self, name):
                if name == 'getParent':
                    self.attempts += 1
                raise AttributeError(name)

        class Square:
            def getX(self): return 12
            def getY(self): return 14

        class Parent:
            def getSquare(self): return Square()

        class Container:
            def __init__(self, capacity=20):
                self.capacity, self.items = capacity, []
            def getParent(self): return Parent()
            def getType(self): return 'crate'
            def getMaxWeight(self): return self.capacity
            def AddItem(self, item): self.items.append(item)

        lua.globals().instanceof = lambda obj, kind: kind == 'ItemContainer' and isinstance(obj, Container)
        lua.execute(HANDLER.read_text(encoding='utf-8'))
        lua.execute('table.insert(KnoxMapGunCache.boxes, { id="test", x=10, y=10, w=8, h=8 })')
        wrong, small, valid = WrongContainer(), Container(2), Container()
        for container in (wrong, small, valid, valid):
            lua.globals().handler('room', 'crate', container)
        self.assertEqual(wrong.attempts, 0)
        self.assertEqual(small.items, [])
        self.assertEqual(valid.items, ['Base.AssaultRifle', 'Base.556Clip', 'Base.556Clip', 'Base.556Box'])
