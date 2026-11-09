"""Reproducible SDK-only build, no Gradle daemon or third-party Android libraries."""
import argparse
import datetime as dt
import os
from pathlib import Path
import subprocess
import zipfile
import tempfile
import shutil


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sdk',type=Path,default=Path.home()/'.cache/xianqi-build/android-sdk')
    parser.add_argument('--jdk',type=Path,default=Path('C:/Program Files/Android/openjdk/jdk-21.0.8'))
    parser.add_argument('--work',type=Path); parser.add_argument('--destination',type=Path); parser.add_argument('--r8',type=Path,default=Path.home()/'.tools/android-build/r8-8.7.18.jar'); parser.add_argument('--test',action='store_true');args=parser.parse_args()
    here=Path(__file__).resolve().parent
    out=(args.work/dt.datetime.now().strftime('%Y%m%d-%H%M%S')) if args.work else Path(tempfile.mkdtemp(prefix='audio-android-build-'));out.mkdir(parents=True,exist_ok=True)
    tools=args.sdk/'build-tools/34.0.0'; platform=args.sdk/'platforms/android-35/android.jar';java=args.jdk/'bin/java.exe'
    def run(*parts):subprocess.run([str(p) for p in parts],check=True,cwd=here)
    manifest=(here/'app/src/main/AndroidManifest.xml').read_text(encoding='utf-8')
    manifest=manifest.replace('<manifest xmlns:android=', '<manifest package="org.audiomemory.mobile" android:versionCode="2" android:versionName="0.2.0" xmlns:android=')
    manifest=manifest.replace('    <application','    <uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35" />\n    <application')
    if args.test:manifest=manifest.replace('<application android:label=', '<application android:debuggable="true" android:label=').replace('</manifest>','<instrumentation android:name="org.audiomemory.mobile.MobileChecks" android:targetPackage="org.audiomemory.mobile" android:label="Isolated checks" /></manifest>')
    (out/'AndroidManifest.xml').write_text(manifest,encoding='utf-8')
    classes=out/'classes';classes.mkdir();(classes/'org/audiomemory/mobile').mkdir(parents=True);dex=out/'dex';dex.mkdir()
    sources=list((here/'app/src/main/java').rglob('*.java'))
    if args.test:sources+=list((here/'app/src/debug/java').rglob('*.java'))
    run(args.jdk/'bin/javac.exe','-encoding','UTF-8','-source','8','-target','8','-classpath',platform,'-d',classes,*sources)
    jar=out/'classes.jar'
    with zipfile.ZipFile(jar,'w') as z:
        for p in classes.rglob('*.class'):z.write(p,p.relative_to(classes).as_posix())
    run(java,'-cp',args.r8,'com.android.tools.r8.D8','--min-api','26','--lib',platform,'--output',dex,jar)
    # aapt2 on Windows cannot reliably open resource paths containing non-ASCII characters.
    with tempfile.TemporaryDirectory(prefix='audio-android-res-') as resource_stage:
        resources = Path(resource_stage) / 'res'
        shutil.copytree(here/'app/src/main/res', resources)
        run(tools/'aapt2.exe','compile','--dir',resources,'-o',out/'res.zip')
    apk=out/'unsigned.apk'
    run(tools/'aapt2.exe','link','-I',platform,'--manifest',out/'AndroidManifest.xml','-o',apk,out/'res.zip','--auto-add-overlay')
    with zipfile.ZipFile(apk,'a',compression=zipfile.ZIP_DEFLATED) as z:
        for p in dex.glob('*.dex'):z.write(p,p.name)
    aligned=out/'aligned.apk';run(tools/'zipalign.exe','-f','4',apk,aligned)
    destination=args.destination or here/'dist'/('AudioMemory-Android-Test.apk' if args.test else 'AudioMemory-Android.apk');destination.parent.mkdir(parents=True,exist_ok=True);target=out/'signed.apk'
    (here/'build').mkdir(exist_ok=True)
    keystore=out/'debug.keystore'
    saved_key=here/'build/debug.keystore'
    if saved_key.exists():shutil.copy2(saved_key,keystore)
    if not keystore.exists():run(args.jdk/'bin/keytool.exe','-genkeypair','-keystore',keystore,'-storepass','android','-keypass','android','-alias','androiddebugkey','-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=Audio Memory Development')
    run(java,'-jar',tools/'lib/apksigner.jar','sign','--ks',keystore,'--ks-pass','pass:android','--key-pass','pass:android','--out',target,aligned)
    run(java,'-jar',tools/'lib/apksigner.jar','verify','--verbose',target)
    shutil.copy2(target,destination)
    if not saved_key.exists():shutil.copy2(keystore,saved_key)
    print(destination)


if __name__=='__main__':main()
