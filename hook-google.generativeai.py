from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect all google-generativeai related packages
datas, binaries, hiddenimports = collect_all('google.generativeai')

# Add submodules
hiddenimports += collect_submodules('google.generativeai')
hiddenimports += collect_submodules('google.ai.generativelanguage')
hiddenimports += collect_submodules('google.api_core')
hiddenimports += collect_submodules('google.auth')
hiddenimports += collect_submodules('google.protobuf')
hiddenimports += ['google.generativeai', 'google.ai.generativelanguage', 'google.ai.generativelanguage_v1', 'google.ai.generativelanguage_v1beta']
