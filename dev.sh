set -e

su6 fix &
./prettier.sh

pushd src/twofas/web
  bunx tsc
  # bunx tsc app.ts
popd

pip install .[gui]
2fas --gui
