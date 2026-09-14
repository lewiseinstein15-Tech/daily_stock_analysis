#!/bin/bash
# Build Jexi v1.0.0 APK — native shell + packaged Expo web export. No Gradle needed.
set -e

SDK=/home/z/my-project/android-sdk
BT=$SDK/build-tools/35.0.0
PLAT=$SDK/platforms/android-34/android.jar
JDK=$(ls -d /home/z/my-project/jdk/jdk-21*/ | head -1)
export PATH="${JDK}bin:$PATH"
ROOT=/home/z/my-project/apk-build
APP=$ROOT/app
OUT=$ROOT/out
VER=1.0.0

echo "== [1/7] clean =="
rm -rf "$OUT"
mkdir -p "$OUT"

echo "== [2/7] compile resources =="
"$BT/aapt2" compile --dir "$APP/src/main/res" -o "$OUT/res.zip"

echo "== [3/7] link resources + manifest + assets =="
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLAT" \
  --manifest "$APP/src/main/AndroidManifest.xml" \
  -A "$APP/src/main/assets" \
  --auto-add-overlay \
  "$OUT/res.zip"

echo "== [4/7] compile java =="
mkdir -p "$OUT/classes"
find "$APP/src/main/java" -name "*.java" > "$OUT/sources.txt"
"${JDK}bin/javac" -source 17 -target 17 -Xlint:-options \
  -classpath "$PLAT" \
  -d "$OUT/classes" \
  @"$OUT/sources.txt" 2>&1 | grep -v "bootstrap class path" || true
test -f "$OUT/classes/com/jexi/app/MainActivity.class"

echo "== [5/7] dex =="
"${JDK}bin/jar" cf "$OUT/classes.jar" -C "$OUT/classes" .
"$BT/d8" --release --min-api 24 --lib "$PLAT" --output "$OUT" "$OUT/classes.jar"
test -f "$OUT/classes.dex"

echo "== [6/7] package + align =="
(cd "$OUT" && zip -q base.apk classes.dex)
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "== [7/7] sign =="
if [ ! -f "$ROOT/keystore.jks" ]; then
  "${JDK}bin/keytool" -genkeypair -v -keystore "$ROOT/keystore.jks" -alias jexi \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass jexi2026 -keypass jexi2026 \
    -dname "CN=Jexi, OU=Jexi, O=Jexi, L=Nairobi, C=KE" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$ROOT/keystore.jks" --ks-key-alias jexi \
  --ks-pass pass:jexi2026 --key-pass pass:jexi2026 \
  --out "$ROOT/Jexi-v$VER.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify "$ROOT/Jexi-v$VER.apk" && echo "SIGN_OK"

ls -la "$ROOT/Jexi-v$VER.apk"
echo "APK_BUILD_OK: $ROOT/Jexi-v$VER.apk"
