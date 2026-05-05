# -*- coding: utf-8 -*-
"""Simple unit test for local_storage_helper using stubbed streamlit and
streamlit_local_storage modules so it can run in a plain Python environment.

Run with:
    python -u C:\Repos\QuizFour\tests\test_local_storage_helper.py
"""
import sys
import json


class _StubStreamlitModule:
    def __init__(self):
        # simple dict-like session_state
        self.session_state = {}

    def get_option(self, name):
        if name == "theme.base":
            return "light"
        raise KeyError(name)


class _StubLocalStorage:
    def __init__(self, key=None):
        self._init_key = key
        self._store = {}

    def getItem(self, k):
        return self._store.get(k)

    def setItem(self, k, v):
        # mimic behavior: store value as-is
        self._store[k] = v


def main():
    # insert stubs into sys.modules before importing module under test
    stub_st = _StubStreamlitModule()
    sys.modules['streamlit'] = stub_st

    # create a simple module object for streamlit_local_storage
    import types
    sls_mod = types.SimpleNamespace(LocalStorage=_StubLocalStorage)
    sys.modules['streamlit_local_storage'] = sls_mod

    # Now import the helper (it will use our stubs)
    import importlib
    # ensure project root is on sys.path so imports find local modules
    from pathlib import Path
    proj_root = str(Path(__file__).resolve().parent.parent)
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)
    local_storage_helper = importlib.import_module('local_storage_helper')

    # create LocalStorage instance and ensure session state loaded
    ls = local_storage_helper.init_local_storage()
    local_storage_helper.ensure_loaded(ls)

    user = 'alice'
    settings = {
        'order_mode': 'シャッフル',
        'show_japanese': True,
        'voice_mode': False,
    }

    # save user settings and persist
    local_storage_helper.set_user_settings(user, settings)
    local_storage_helper.save_app_data(ls)

    # verify raw storage contains the serialized JSON under the expected key
    raw = ls.getItem(local_storage_helper._DATA_KEY)
    if raw is None:
        print('FAILED: no data saved in LocalStorage')
        sys.exit(2)

    try:
        data = json.loads(raw)
    except Exception as exc:
        print('FAILED: saved data is not valid JSON:', exc)
        sys.exit(2)

    us = data.get('user_settings', {})
    if user not in us:
        print('FAILED: user settings not present in saved data')
        sys.exit(2)

    loaded = local_storage_helper.load_app_data(ls)
    loaded_us = loaded.get('user_settings', {})
    if loaded_us.get(user, {}) != settings:
        print('FAILED: loaded user settings do not match saved settings')
        print('expected:', settings)
        print('got:', loaded_us.get(user))
        sys.exit(2)

    # Also test get_user_settings API
    got = local_storage_helper.get_user_settings(user)
    if got != settings:
        print('FAILED: get_user_settings returned different data')
        print('expected:', settings)
        print('got:', got)
        sys.exit(2)

    print('OK: save/load/get_user_settings roundtrip passed')


if __name__ == '__main__':
    main()

