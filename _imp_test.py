import traceback
try:
    import server.main as m
    print('import_ok')
except Exception as e:
    print('import_error:', repr(e))
    traceback.print_exc()
