# -*- coding: utf-8 -*-
"""Test that order_mode values (特に「順番通り」) are persisted via local_storage_helper.

Run with:
    python -u C:\Repos\QuizFour\tests\test_order_mode_persistence.py
"""
import sys
import json


class _StubStreamlitModule:
    def __init__(self):
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
        self._store[k] = v


def main():
    # install stubs
    stub_st = _StubStreamlitModule()
    sys.modules['streamlit'] = stub_st
    import types
    sls_mod = types.SimpleNamespace(LocalStorage=_StubLocalStorage)
    sys.modules['streamlit_local_storage'] = sls_mod

    # ensure project root is on path
    from pathlib import Path
    proj_root = str(Path(__file__).resolve().parent.parent)
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)

    import importlib
    lsh = importlib.import_module('local_storage_helper')

    ls = lsh.init_local_storage()
    lsh.ensure_loaded(ls)

    user = 'bob'
    settings = {'order_mode': '順番通り', 'show_japanese': False, 'voice_mode': False}

    lsh.set_user_settings(user, settings)
    lsh.save_app_data(ls)

    raw = ls.getItem(lsh._DATA_KEY)
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

    if us[user].get('order_mode') != '順番通り':
        print('FAILED: saved order_mode is not 順番通り')
        print('got:', us[user].get('order_mode'))
        sys.exit(2)

    loaded = lsh.load_app_data(ls)
    loaded_us = loaded.get('user_settings', {})
    if loaded_us.get(user, {}) != settings:
        print('FAILED: loaded user settings do not match saved settings')
        print('expected:', settings)
        print('got:', loaded_us.get(user))
        sys.exit(2)

    got = lsh.get_user_settings(user)
    if got != settings:
        print('FAILED: get_user_settings returned different data')
        print('expected:', settings)
        print('got:', got)
        sys.exit(2)

    print('OK: order_mode persistence (順番通り) passed')


if __name__ == '__main__':
    main()

