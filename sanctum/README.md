# Sanctum Island — HD Remaster (grafik High)

**Unduh:** [`release/Sanctum_Island_Map_HD.zip`](release/Sanctum_Island_Map_HD.zip) (60 MB) — menggantikan
`Sanctum_Island_Map.zip`.

Struktur zip, nama file, urutan entri, dan kompresinya sama persis dengan file asli (`Scenes/android/...`). Cara
pasangnya juga sama: timpa file lama.

Sesuai permintaan, yang diubah **hanya scene grafik High** (`PVP_049_add.unity3d`). Tujuh file lain disalin
identik byte-per-byte: versi Low `PVP_049_low`, data jalur/tembok A* (`*wall_add`), `PVP_003_add`, `PVP_009`, dan
`GalleryCenter`.

![Peta sebelum / sesudah](docs/previews/1_peta_sebelum_sesudah.png)

## 1. Tekstur sangat HD

Semua tekstur asli berformat ASTC 8x8 (kompresi paling kasar) tanpa mipmap. Tanah hanya punya ±39 texel per meter,
jadi di layar HP ia diperbesar ±2×. Itu sebabnya tanah terlihat buram dan berblok.

| Tekstur | Sebelum | Sesudah |
|---|---|---|
| 16 petak tanah + sungai (`hedaobake`) | 1024², ASTC 8x8 | **2048²**, ASTC 6x6, mipmap penuh |
| 40 props (patung, pohon, bangunan, tembok, kamp buff, tebing, kristal, …) | 512², ASTC 8x8 | **1024²**, ASTC 8x8, mipmap penuh |
| Langit / pulau melayang (`skybox`) | 512² | **1024²**, ASTC 6x6 |
| Rumput & daun (cut-out) | 512² | **1024²**, ASTC 6x6, alpha di-upscale terpisah supaya tepi daun tetap tajam |
| 7 lightmap | 1024² / 512², ASTC 8x8 | ukuran sama, artefak blok dihaluskan, ASTC 6x6 |
| Mask, noise air | 256² / 64² | 512² / 256² (noise air tetap seamless) |

Cara upscale-nya:

- **AI super-resolution:** Real-ESRGAN compact (`realesr-general-x4v3`, lisensi BSD-3), dijalankan lokal via
  ONNX Runtime. Saya pakai campuran 20% model *denoise* dan 80% model *no-denoise*, supaya tepi retakan batu dan
  garis ukiran jadi tajam tapi butiran rumput dan batu tidak hilang. Hasil ×4 diturunkan ke ×2 (supersampling).
- **Detail restore:** tekstur halus (rumput, kerikil) yang dihaluskan AI dikembalikan dari versi Lanczos, lalu
  dipertajam ringan.
- **Kualitas kompresi:** dibanding versi HD tanpa kompresi, ASTC 6x6 pada 2048 mencapai PSNR 43 dB (8x8: 40 dB).

## 2. Pewarnaan lebih keren

Grading sinematik yang sama untuk tanah, props, langit, dan lightmap, jadi semuanya tetap serasi:

- *Dehaze*: lapisan kabut pucat dihilangkan, lalu kontras mid-tone dinaikkan sambil menjaga kecerahan.
- *Vibrance*: warna pucat lebih hidup, warna yang sudah kuat tidak berlebihan.
- Rumput dan pohon lebih hijau segar. Air sungai lebih toska dan jernih.
- *Split-tone*: highlight hangat (cahaya matahari), bayangan sedikit dingin. Lightmap props ikut diberi nada yang
  sama.
- *Clarity* (kontras lokal): ukiran jalur lane, retakan batu, dan tepi semak lebih tegas.

![Close-up 1](docs/previews/2_closeup_1.png)
![Close-up 2](docs/previews/3_closeup_2.png)
![Tekstur props](docs/previews/4_tekstur_props.png)

## 3. Halus dan ringan

- **Mipmap + trilinear** untuk tanah dan props. Tekstur tidak lagi berkilau/bergerigi saat kamera bergeser.
  Mipmap juga lebih ramah cache GPU.
- **Anisotropic filtering** 4× untuk tanah, 2× untuk props. Bagian atas layar yang terlihat miring tetap tajam.
- Rumput dan daun cut-out sengaja tanpa mipmap, supaya tidak menipis.
- **Efek baru dibuat seringan mungkin:**
  - Total hanya ±237 partikel hidup di seluruh peta, dari 13 sistem.
  - Tanpa modul Noise atau Collision. Gerak meliuk dibuat dari kurva kecepatan acak, yang lebih murah.
  - Simulasi world-space dengan *prewarm*, jadi efek sudah ada sejak map dimuat.
  - Culling otomatis Unity.
  - Hanya 4 tekstur kecil (64–128 px).
- **Konsekuensi memori:** tekstur High naik dari 8,3 MB menjadi 57,5 MB (tanah 40 MB, props 13,7 MB). Bundle
  High naik dari 10,1 MB ke 55,5 MB. Untuk perangkat yang memakai grafik High, ini masih wajar. Versi Low tidak
  tersentuh.

## 4. Efek baru di peta

| Efek | Lokasi | Tampilan |
|---|---|---|
| Kunang-kunang (4 area) | keempat area jungle | titik cahaya emas-hijau, melayang meliuk, berkedip |
| Kilau sungai | permukaan sungai | bintang kecil toska-putih berkelip, berputar |
| Kabut sungai | rendah di atas sungai | gumpalan kabut tipis bergerak pelan, membesar sambil memudar |
| Aura lubang Lord / Turtle (2) | kedua *pit* | partikel cahaya toska → ungu naik perlahan |
| Kilau base (2) | sekitar orb kedua base | bintang putih-emas naik berputar. Warnanya netral, jadi tetap cocok saat warna tim ditukar |
| Debu cahaya | seluruh peta | butiran cahaya kecil melayang di udara |
| Daun berguguran (2) | tepi atas & bawah peta | daun hijau → kuning keemasan jatuh berputar dan bergoyang |

![Efek baru (simulasi)](docs/previews/5_efek_baru_simulasi.png)

*Gambar efek di atas adalah simulasi tampak atas dari parameter efek yang terpasang, bukan screenshot game.*

Cara efek disisipkan:

- Efek adalah objek Unity biasa di scene High: GameObject + ParticleSystem + Renderer, ditambah material dan tekstur
  di sharedAssets.
- Tipe ParticleSystem diambil dari bundle Unity 2019.4.33f1 asli, dengan hash tipe yang identik dengan bundle game
  lainnya.
- Shader-nya memakai shader efek additive / alpha-blend yang sudah ada di bundle shader yang memang dipakai map ini.
  Shader itu ditambahkan ke PreloadData scene supaya ikut dimuat.
- Semua efek ada di layer yang sama dengan props peta (layer 10).

## Validasi

`tools/validate_map.py` ([log](docs/validate.log)) — **0 masalah**:

- 7 file selain scene High identik byte-per-byte.
- Header bundle dan nama file internal sama. Tidak ada objek asli yang hilang atau berubah tipe.
- Semua objek non-tekstur asli identik byte-per-byte. Pengecualiannya PreloadData, yang memang ditambah 2 shader.
- 1290 objek terbaca ulang lewat typetree.
- 74 tekstur ter-decode. Ukuran data cocok dengan format dan mipmap. Isi dan orientasinya berkorelasi dengan
  aslinya, tidak ada yang terbalik.
- Objek yang ditambahkan persis sesuai rencana: 13 sistem efek + 1 root, 4 material, 4 tekstur.
- Semua referensi efek valid: komponen, hierarki transform, material → tekstur, material → shader additive/blend,
  dan shader ada di PreloadData.
- Kapasitas partikel cukup (tidak ada yang kehabisan slot). Total partikel di bawah anggaran 260.

Catatan: validasi ini memeriksa struktur file. Tampilan di dalam game belum bisa saya uji langsung di HP.

## Build ulang dari file asli

```bash
pip install -r tools/requirements.txt
# bobot Real-ESRGAN (resmi, BSD-3) — dimuat tanpa torch, lewat unpickler terbatas (tanpa eksekusi kode)
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth
#   sha256 8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292  realesr-general-x4v3.pth
#   sha256 1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca  realesr-general-wdn-x4v3.pth
python tools/sr_model.py realesr-general-x4v3.pth realesr-general-wdn-x4v3.pth 0.2 sr_dni20.onnx
#   sha256 640731aa2d0c7026899e445bf7fddb6707b1579a89360803862247eb922768a4  sr_dni20.onnx
unzip Sanctum_Island_Map.zip -d orig        # -> orig/Scenes/android/...
python tools/build_map.py orig/Scenes/android out/Scenes/android report.json sr_dni20.onnx 4
python tools/validate_map.py orig/Scenes/android out/Scenes/android
python tools/map_previews.py orig/Scenes/android/PVP_049_add.unity3d out/Scenes/android/PVP_049_add.unity3d previews
python tools/pack_like.py Sanctum_Island_Map.zip out Sanctum_Island_Map_HD.zip
```

Build memakan ±10 menit dengan 4 core. Hasil zip (SHA-256
`3d029ce428a02188836eec64e6a825f20a7e40bad7ae2f8905ffcaa144698234`) bisa direproduksi. Inferensi AI-nya
deterministik pada jumlah thread yang sama.

| Tool | Fungsi |
|---|---|
| `sr_model.py` | muat bobot Real-ESRGAN tanpa torch, campur denoise, ekspor ONNX, upscale ×2 per tile |
| `map_hd.py` | grading sinematik, detail restore, sharpening |
| `map_fx.py` + `map_fx_templates.json` | efek ambient baru dan penyisipannya ke scene (template tipe ParticleSystem Unity 2019.4.33f1) |
| `build_map.py` | build lengkap scene High |
| `validate_map.py` | validasi di atas |
| `map_render.py`, `map_previews.py` | render peta tampak atas dan gambar pratinjau |
| `pack_like.py` | zip dengan entri / urutan / kompresi sama seperti zip asli |
