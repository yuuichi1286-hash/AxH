# AxH — Hidan Revamp v2

**Unduh:** [`release/Hidan.Revamp.v2.zip`](release/Hidan.Revamp.v2.zip)

Isinya 99 file dengan struktur folder (`HIDAN/Art`, `HIDAN/UI`, `HIDAN/Audio`) yang sama persis dengan
`Hidan.Revamp.zip` di rilis [AxH](https://github.com/yuuichi1286-hash/AxH/releases/tag/AxH). Cara pasangnya juga
sama: timpa file lama dengan file di zip ini.

![Model sebelum vs sesudah](docs/previews/1_model_sebelum_sesudah.png)

## 1. Model lebih mirip Hidan (kualitas Normal & High)

- **Mata**: iris merah ala Sharingan diganti ungu-violet, warna mata kanon Hidan. Berlaku untuk wajah normal dan
  wajah ritual (tengkorak).
- **Kulit** lebih pucat dan tidak oranye lagi, sesuai kulit Hidan yang terang.
- **Liontin Jashin** (lingkaran + segitiga terbalik) dengan tali di dada. Liontin ini juga terlihat di mode ritual
  (skill 3).
- **Shading toon 3 tingkat.** Sebelumnya, karena arah cahaya toon lurus dari atas, wajah dan badan depan tampil
  ~50% gelap. Sekarang wajah dan badan lebih terang dan lebih jelas dari kamera MLBB.
- **Tekstur** diubah jadi ETC2 RGB dengan mipmap penuh. Ukurannya turun dari 1 MB ke 0,68 MB (kanal alpha memang
  tidak dipakai), dan tekstur tidak lagi "berkilau"/bergerigi saat dilihat dari jauh.
- Model *extra low* (`hero_argus_skin_extlow_add`) tidak diubah. Model itu sudah Hidan versi detail dengan mata
  ungu.

## 2. Animasi tidak patah-patah lagi

Penyebab yang ditemukan di data animasi:

| Masalah | Contoh |
|---|---|
| **Snap**: tulang berputar 100–190° dalam 1–2 frame sehingga terlihat seperti teleport | attack4/5, skill2, skill3, skill4_2 |
| **Kink**: kecepatan gerak berubah mendadak antar keyframe, terasa robotik | hampir semua serangan |
| **Sambungan loop lari**: lutut di akhir siklus beda 6,5° dari awal siklus, jadi tersendat tiap 0,88 dtk | run, run2 |
| **Putaran sabit ekstrem**: ~9 putaran dalam 0,58 dtk, tampak "strobo" di 30 fps | skill1_1 |

Perbaikan:

- Setiap snap diganti tween *ease-in/out* (slerp), jadi tampil sebagai ayunan cepat yang tetap terlihat.
- Putaran ekstrem dikurangi jumlah putarannya. Pose awal dan akhir tidak berubah.
- Smoothing ringan dipakai di semua tulang, dengan batas kecepatan supaya putaran cepat yang memang disengaja tidak
  hilang.
- Sambungan loop run, run2, dan fight_idle sekarang 0°.
- Pergantian mesh normal ↔ ritual di skill3 tetap tepat waktu. Pergantian disimpan sebagai *step* presisi, jadi
  tidak ada frame dengan dua mesh tampil bersamaan.
- Transisi Animator: crossfade 0,10 → 0,15 dtk. Masuk ultimate sebelumnya potong keras (0 dtk), sekarang 0,08 dtk.
  Masuk recall 0,25 dtk, keluar recall 0,2 dtk.

| Klip | Durasi | Putaran terbesar per frame (60 fps), sebelum → sesudah |
|---|---|---|
| attack1 | 0.65 dtk | 59° → 30° |
| attack2 | 0.65 dtk | 77° → 34° |
| attack3 | 0.65 dtk | 63° → 30° |
| attack4 | 1.25 dtk | 118° → 38° |
| attack5 | 1.25 dtk | 119° → 38° |
| skill1_1 | 1.75 dtk | 104° → 56° |
| skill1_2 | 0.75 dtk | 38° → 36° |
| skill1_3 | 1.13 dtk | 30° → 30° |
| skill1_4 | 0.45 dtk | 23° → 15° |
| skill2 | 1.25 dtk | 98° → 40° |
| skill3 (ult) | 1.32 dtk | 144° → 38° |
| skill4_2 | 1.10 dtk | 90° → 64° |
| run / run2 | 0.88 dtk (loop) | 20° → 18°, sambungan loop 6,5° → 0° |
| fight_idle | 15.12 dtk (loop) | 4° → 4° |
| recall | 3.05 → 6.50 dtk | lihat bagian 3 |

![Snap attack4 dihaluskan](docs/previews/2_attack_snap_dihaluskan.png)

## 3. Recall

- **Sebelumnya**: klip 3,05 dtk yang looping. Pose akhirnya (kuda-kuda) berbeda ~155° dari pose awal (berdiri),
  jadi badan **meloncat** kembali ke pose awal setiap 3 detik.
- **Sekarang**: klip 6,5 dtk tanpa loop. Gerakan aslinya dihaluskan, lalu masuk ke kuda-kuda dengan napas halus
  (dada, kepala, bahu, dan pinggul bergerak sedikit), lalu menetap tenang. Crossfade masuk ke recall juga dibuat
  lebih lembut (0,25 dtk).

![Recall tanpa loncat](docs/previews/3_recall_tanpa_loncat.png)

## 4. Efek (VFX): fade, lebih tegas, lebih ringan

- **Fade-in & fade-out di semua efek.** Ke-463 ParticleSystem sekarang mulai dan berakhir di alpha 0: 172 diberi
  fade-in baru, 16 diberi fade-out baru, dan yang sudah punya fade dipertahankan. Ada 8 efek mesh (puing ult,
  sayap ult, plane skill) yang tadinya langsung muncul penuh; sekarang semuanya diberi fade-in.
- **Lebih keren & terdefinisi.** Percikan dan bara lahir "panas" (merah keputihan) lalu turun ke merah darah.
  Semua partikel menggelap ke merah tua sebelum hilang, jadi setiap ledakan terbaca jelas dan tidak lagi berupa
  noda merah yang datar.
- **Optimasi:**
  - NoiseModule pada 104 sistem diturunkan dari Medium/High ke Low.
  - 83 emitter yang terlalu padat dikompres, dengan ukuran partikel sedikit dibesarkan supaya efek tetap terasa
    penuh. Batas maxParticles dipasang pada 89 sistem.
  - 2 tekstur 1254² ETC2 RGBA8 (masing-masing 1,5 MB) diubah jadi 1024² ASTC 5x5.
  - Perkiraan jumlah partikel turun ~29% secara total, dan −55% untuk cast ultimate.

![Optimasi dan fade VFX](docs/previews/4_vfx_optimasi_dan_fade.png)

## Validasi

- Setiap bundle dimuat ulang dan setiap objek dibaca ulang. Hasilnya dibandingkan dengan aslinya: flag kompresi dan
  header, nama file internal (CAB), serta set objek semuanya identik. Pengecekan dijalankan dengan
  `tools/validate_all.py`.
- Klip animasi divalidasi: ukuran muscle clip (rumus dikalibrasi dari semua 90+ klip di mod ini), jumlah kurva,
  norma quaternion, dan tidak ada flip hemisphere. Orientasi tekstur model juga dicek.
- Build-nya deterministik: menjalankan `tools/build.py` ulang menghasilkan 99 file yang identik byte demi byte.
- **Belum dites langsung di dalam game.** Di lingkungan build tidak ada perangkat Android maupun MLBB. Kalau ada
  skill yang terlihat aneh, sebutkan nama skill-nya.

File yang sengaja **tidak diubah**: audio, UI, `hero_argus.unity3d` (animasi Argus asli), model extra low, dan
`heroshow_ip03_add` (latar lobby).

> Catatan: memodifikasi file game melanggar ketentuan layanan Moonton dan bisa berisiko untuk akun. Gunakan dengan
> risiko sendiri.

## Build ulang dari Hidan.Revamp.zip asli

```bash
pip install -r tools/requirements.txt
unzip Hidan.Revamp.zip -d orig
python tools/build.py orig/HIDAN out/HIDAN out/report.json        # semua pass
python tools/validate_all.py orig/HIDAN out/HIDAN                  # validasi
python tools/make_previews.py orig/HIDAN out/HIDAN docs/previews   # gambar sebelum/sesudah
```

| File | Isi |
|---|---|
| `tools/anim_fix.py` | decode/encode klip Mecanim, despin, despike, smoothing, loop seam, recall baru, transisi Animator |
| `tools/model_tex.py` | mata, kulit, liontin Jashin, sharpen, encoder ETC2 + mipmap |
| `tools/vfx_fix.py` | fade alpha, warna, noise, budget partikel, fade efek mesh |
| `tools/clipio.py`, `meshio.py`, `fk.py` | parser kurva streamed/dense, vertex buffer, forward kinematics + skinning |
| `tools/toon_preview.py`, `filmstrip.py`, `render_obj.py` | renderer software untuk pratinjau |
| `docs/build_report.json` | rincian perubahan per bundle |
