# Sanctum Island — HD Remaster v4 "clean premium" (grafik High)

**Unduh:** [`release/Sanctum_Island_Map_HD.zip`](release/Sanctum_Island_Map_HD.zip) (67 MB) — menggantikan
`Sanctum_Island_Map.zip`.

Struktur zip, nama file, urutan entri, dan kompresinya sama persis dengan file asli (`Scenes/android/...`). Cara
pasangnya juga sama: timpa file lama.

Sesuai permintaan, yang diubah **hanya scene grafik High** (`PVP_049_add.unity3d`). Tujuh file lain disalin
identik byte-per-byte: versi Low `PVP_049_low`, data jalur/tembok A* (`*wall_add`), `PVP_003_add`, `PVP_009`, dan
`GalleryCenter`.

**Seluruh peta High ikut berubah**, bukan hanya beberapa bagian:

- 16 dari 16 petak tanah, termasuk sungai.
- 40 dari 40 tekstur props: bangunan base, patung, tembok, batu jungle, pohon, tebing luar, pilar, kristal.
- Langit dan pulau melayang, 7 lightmap, rumput dan daun 3D, serta pantulan air.

Gambar di bawah adalah seluruh peta beserta bangunannya: atas asli, bawah remaster.

![Seluruh peta sebelum / sesudah](docs/previews/0_seluruh_peta.png)

Ada beberapa hal yang memang **bukan bagian dari file map**, sehingga tetap seperti biasa: turret/tower, inti base,
monster jungle, Lord/Turtle, minion, hero, dan efek skill. Semuanya dimuat dari file game lain. Lubang hitam di
gambar tampak atas adalah posisi tower.

![Peta sebelum / sesudah](docs/previews/1_peta_sebelum_sesudah.png)

## Yang baru di v4: tekstur bersih, tidak burik lagi

Di versi sebelumnya tekstur terlihat **burik**: berbintik, bergaris halus, dan kotor kalau dilihat dekat. Ada tiga
penyebab, dan ketiganya sudah dibuang:

1. **Butiran buatan.** Untuk menambah "detail", versi sebelumnya menanam helai rumput dan butiran tanah dari noise,
   lalu mempertajamnya. Di layar HP, hasilnya terlihat sebagai pola garis halus yang kotor.
2. **AI yang "mengarang" tekstur.** Upscaler AI dipakai dengan 80% model tanpa *denoise*. Akibatnya kotak-kotak
   kompresi ASTC 8x8 dari tekstur asli ikut dibesarkan dan berubah menjadi pola acak.
3. **Kontras lokal dan sharpening di semua piksel.** Bercak dan butiran jadi makin menonjol.

Yang dilakukan v4, untuk **semua** tekstur (tanah, props, langit, rumput dan daun 3D):

- **Upscale AI yang bersih.** Campuran AI sekarang 45% model *denoise*. Artefak kompresi hilang, tapi sapuan
  lukisan aslinya tetap ada.
- **Filter painterly Kuwahara.** Setiap piksel mengambil warna dari sisi lingkungannya yang paling rata. Bintik,
  bercak, dan sisa kompresi berubah menjadi bidang lukisan yang bersih. Tepi tetap tajam (ukiran, retakan, tepi batu,
  trim emas), karena filter ini tidak pernah merata-ratakan melintasi tepi.
- **Tanpa noise buatan sama sekali.** Fungsi pembuat butiran dari versi sebelumnya sudah dihapus dari kode.
- **Sharpening hanya di struktur nyata.** Ukiran lane, tepi batu, dan trim dipertegas. Area rata seperti rumput dan
  air tidak pernah dipertajam.
- **Ukiran batu lebih timbul.** Relief di batu lane, paving, dan ukiran lantai hampir 3× lebih dalam daripada di
  rumput, jadi batu terlihat dipahat sementara rumput tetap lembut.
- **Palet premium:**
  - Rumput ke arah hijau emerald.
  - Tanah coklat tetap hangat, jadi jalur lane tidak berubah jadi hijau kusam.
  - Air dan dasar pit berwarna toska gelap yang bersih, tanpa bercak.
- **Ornamen berkilau.** Trim emas dan rune biru di lantai, bangunan, patung, dan kristal lebih bercahaya, dengan
  halo lembut.
- **Props sekarang ASTC 6x6** (sebelumnya 8x8), jadi tepi bangunan dan trim tidak berblok.

Hasil terukur pada 16 petak tanah:

- Energi butiran per piksel **turun 59%** dibanding versi sebelumnya.
- Kecerahan rata-rata hanya **1,5% lebih gelap**, jadi nuansa gelap yang diminta tetap sama.
- Kompresi ASTC 6x6 pada tekstur yang bersih mencapai PSNR **45–50 dB** terhadap versi tanpa kompresi.

Perbandingan dengan versi sebelumnya (kiri) dan v4 (kanan):

![v4 vs sebelumnya: lane + jungle, skala game](docs/previews/10_v4_vs_sebelumnya_lane.png)
![v4 vs sebelumnya: pit Lord/Turtle + sungai](docs/previews/11_v4_vs_sebelumnya_pit.png)
![v4 vs sebelumnya: base](docs/previews/12_v4_vs_sebelumnya_base.png)

Di skala game (1 m = 100 px, kira-kira satu texel tanah per piksel layar), dibanding peta asli:

![Close-up skala game](docs/previews/9_closeup_skala_game.png)

## Fitur yang tetap ada dari versi sebelumnya

- **Pewarnaan lebih gelap di seluruh peta:** tanah, props/bangunan, tebing, dan langit, rata-rata ±33–43% lebih
  gelap dari aslinya, dengan bayangan lebih dalam. Warnanya tetap kaya, jadi tidak kusam.
- **Bayangan setiap bangunan:** 181 bangunan dan props memberi bayangan nyata ke tanah, mengikuti arah cahaya peta.
- **AO:** gelap kontak di kaki bangunan, ditambah AO celah di dalam tekstur.
- **Emboss / relief:** permukaan batu, ukiran lane, dan props terlihat timbul.
- **Kilau ala PBR:** batu dan logam memantulkan cahaya, sedangkan rumput tetap matte.
- **Pantulan air ala SSR:** cubemap pantulan sungai 32 → 128 px, lebih tajam dan diberi grading gelap yang sama.
- **12 efek ambient** (lihat bagian 6).

### Perbaikan: garis lurus / "terpotong" di dalam game

Di salah satu versi sebelumnya ada area berkabut dengan garis lurus di sekitar sungai dan pit, seperti layar
terpotong. Ada dua penyebab, dan keduanya sudah diperbaiki:

1. **Efek kabut sungai.** Partikelnya besar (hingga ±8 m) dan selalu menghadap kamera. Shader efek game tidak punya
   *soft particle*, jadi bidang kabut terpotong lurus di tempat ia menembus tanah, pohon, atau batu. Area di
   belakangnya terlihat seperti lapisan kabut bertepi tajam. **Efek kabut dihapus.** Kilau sungai juga dinaikkan
   supaya tidak menembus permukaan air.
2. **Pantulan air.** Mesh permukaan air menutupi sungai, pit, dan tepiannya dalam bentuk persegi panjang. Kalau
   pantulannya lebih terang dari aslinya, tepi persegi itu ikut terlihat. Material air sekarang **kembali ke nilai
   aslinya**, dan cubemap dibuat sedikit lebih gelap, tidak lebih terang.

> **Kenapa "baked":** SSR, shader PBR, dan shadow real-time adalah fitur renderer dan shader game. Keduanya ada di
> engine dan bundle shader MLBB, bukan di file map, jadi tidak bisa dinyalakan dari map. Karena itu semuanya saya
> *bake*: dihitung dari geometri dan arah cahaya asli peta, lalu ditanam ke tekstur dan cubemap. Dari kamera MOBA
> yang tetap, hasilnya terlihat sama, dan beban FPS-nya **nol**.

![Bayangan + AO + emboss/PBR](docs/previews/6_bayangan_ao_1.png)
![Bayangan di base](docs/previews/7_bayangan_ao_2.png)

## 1. Tekstur sangat HD

Semua tekstur asli berformat ASTC 8x8 (kompresi paling kasar) tanpa mipmap. Tanah hanya punya ±52 texel per meter,
jadi di layar HP ia diperbesar ±2×. Itu sebabnya tanah terlihat buram dan berblok.

| Tekstur | Sebelum | Sesudah |
|---|---|---|
| 16 petak tanah + sungai (`hedaobake`) | 1024², ASTC 8x8 | **2048²**, ASTC 6x6, mipmap penuh |
| 40 props (patung, pohon, bangunan, tembok, kamp buff, tebing, kristal, …) | 512², ASTC 8x8 | **1024²**, ASTC 6x6, mipmap penuh |
| Langit / pulau melayang (`skybox`) | 512² | **1024²**, ASTC 6x6 |
| Rumput & daun 3D (cut-out) | 512² | **1024²**, ASTC 6x6, alpha di-upscale terpisah supaya tepi daun tetap tajam |
| 7 lightmap | 1024² / 512², ASTC 8x8 | ukuran sama, artefak blok dihaluskan, ASTC 6x6 |
| Cubemap pantulan air | 32 px, ASTC 8x8 | **128 px**, ASTC 6x6, 8 mip |
| Mask, noise air | 256² / 64² | 512² / 256² (noise air tetap seamless) |

Cara upscale-nya:

- **AI super-resolution:** Real-ESRGAN compact (`realesr-general-x4v3`, lisensi BSD-3), dijalankan lokal via
  ONNX Runtime. Bobotnya campuran 45% model *denoise* dan 55% model *no-denoise*: artefak kompresi hilang, sapuan
  lukisan tetap ada. Hasil ×4 diturunkan ke ×2 (supersampling).
- **Pembersihan painterly (Kuwahara umum, 8 sektor):** radius 2 texel di tanah, 3 texel di props, 2 texel di
  rumput/daun 3D. Langit memakai *guided filter*, supaya gradasinya mulus.
- **Sharpening tepi saja:** sharpening hanya bekerja di piksel yang punya gradien nyata (masker tepi). Area rata
  tidak disentuh.

## 2. Rumput, tanah, dan batu: bersih tapi detail

Satu texel tanah setelah 2× kira-kira 1 cm di dunia game. Pengaturannya:

- **Rumput:** sapuan lukisan aslinya dipertahankan dan dibersihkan, tanpa helai buatan. Rumput hijau murni digeser
  ke palet emerald.
- **Batu lane, paving, ukiran lantai:** relief dalam (emboss 0,11), AO celah, dan kilau batu. Di rumput relief
  dibuat lembut (0,04).
- **Tanah coklat:** tetap hangat, dengan palet tanah sendiri.
- **Sungai dan pit:** bersih dan dalam, berwarna toska gelap. Dasar pit dan ukiran lantainya tetap terlihat.
- **Rumput dan daun 3D** (sprite cut-out): Kuwahara radius 2. Warna di area transparannya memang sudah diisi oleh
  artist aslinya, jadi tidak muncul pinggiran gelap.

![Close-up 1](docs/previews/2_closeup_1.png)
![Close-up 2](docs/previews/3_closeup_2.png)

## 3. Bayangan, AO, emboss, PBR, pantulan

- **Arah cahaya:** diambil dari parameter cahaya shader kristal peta (`_CustomLightDir` = 0,61 / 0,71 / -0,35).
  Artinya cahaya datang dari kanan-depan atas dengan elevasi ±45°, dan bayangan jatuh ke kiri-atas peta.
- **Bayangan bangunan:** setiap segitiga dari 181 mesh bangunan dan props diproyeksikan sepanjang arah cahaya ke
  permukaan tanah. Tinggi tanah diambil dari heightmap mesh tanah, jadi platform base yang lebih rendah juga benar.
  - Geometri yang terkubur di bawah tanah tidak memberi bayangan.
  - Tepi bayangan dibuat lembut (penumbra 2 tingkat).
  - Area bayangan diberi nada sedikit dingin, seperti cahaya langit.
  - Kekuatan bayangan 55%, lalu dipetakan ke tekstur 16 petak tanah lewat posisi dunia setiap texel.
- **AO kontak:** jejak geometri dalam 0,9 m dari tanah dibuat gelap lembut di sekeliling kaki bangunan, tembok,
  batu, dan pohon (40%).
- **AO celah:** retakan dan sambungan batu di dalam tekstur menjadi lebih gelap.
- **Emboss / relief:** normal dihitung dari luminansi tekstur yang sudah bersih, lalu disinari dari arah cahaya
  peta. Untuk tanah, arah cahaya dihitung per petak di ruang tekstur. Batu dan ukiran mendapat relief lebih dalam
  daripada rumput.
- **Kilau ala PBR:** specular dengan *half-vector* cahaya-kamera hanya di area batu dan logam (saturasi rendah,
  terang). Rumput dan daun hampir tanpa kilau, jadi materialnya terbedakan.
- **Pantulan air (pengganti SSR):**
  - Cubemap pantulan sungai 32 → 128 px, lebih tajam, dengan grading gelap yang sama seperti tanah.
  - Material air tidak diubah. Mesh air menutupi tepian sungai juga, jadi pantulan yang lebih kuat akan membuat tepi
    mesh-nya terlihat.

![Pantulan air](docs/previews/8_pantulan_air.png)
![Tekstur props](docs/previews/4_tekstur_props.png)

## 4. Pewarnaan

Grading sinematik yang sama untuk tanah, props, langit, dan lightmap, jadi semuanya tetap serasi:

- *Dehaze* dan kontras mid-tone.
- **Mid-tone lebih gelap** dan *exposure* diturunkan:
  - tanah: gamma 1,08, exposure 0,92
  - props dan bangunan: gamma 1,10, exposure 0,90
  - langit: gamma 1,07, exposure 0,92
  - Lightmap props ikut digelapkan.
- **Palet premium** (gradasi warna kurasi): emerald untuk rumput, coklat hangat untuk tanah, toska untuk air.
- **Ornamen berkilau:** trim emas +35% (props +21%), rune biru/toska +40% (props +24%), plus halo lembut.
- *Vibrance*: hijau rumput dan pohon lebih pekat, air lebih toska.
- *Split-tone*: highlight hangat, bayangan sedikit dingin.
- *Clarity* dikurangi (tanah 0,08, props 0,06). Kontras lokal yang terlalu kuat ikut membuat tampilan burik.

## 5. Halus dan ringan

- **Mipmap + trilinear** untuk tanah dan props. Tekstur tidak berkilau/bergerigi saat kamera bergeser, dan lebih
  ramah cache GPU.
- **Anisotropic filtering** 4× untuk tanah, 2× untuk props. Bagian atas layar yang terlihat miring tetap tajam.
- Rumput dan daun cut-out sengaja tanpa mipmap, supaya tidak menipis.
- Bayangan, AO, relief, dan kilau semuanya baked, jadi tidak ada biaya render tambahan.
- **Efek baru dibuat seringan mungkin:**
  - Total ±228 partikel dari 12 sistem.
  - Tanpa modul Noise atau Collision.
  - Simulasi world-space dengan *prewarm*, plus culling otomatis.
  - Hanya 4 tekstur kecil.
- **Konsekuensi memori:**
  - Tekstur High naik dari 8,3 MB menjadi 68,4 MB. Sekitar 11 MB dari kenaikan itu karena props sekarang ASTC 6x6.
  - Bundle High naik dari 10,1 MB menjadi 62,9 MB.
  - Untuk perangkat yang memakai grafik High, ini masih wajar. Versi Low tidak tersentuh.

## 6. Efek baru di peta

| Efek | Lokasi | Tampilan |
|---|---|---|
| Kunang-kunang (4 area) | keempat area jungle | titik cahaya emas-hijau, melayang meliuk, berkedip |
| Kilau sungai | permukaan sungai | bintang kecil toska-putih berkelip, berputar |
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
- Shader-nya memakai shader efek additive / alpha-blend yang sudah ada di bundle shader yang dipakai map ini. Shader
  itu ditambahkan ke PreloadData scene supaya ikut dimuat.
- Semua efek ada di layer yang sama dengan props peta (layer 10).

## Validasi

`tools/validate_map.py` ([log](docs/validate.log)) — **0 masalah**:

- 7 file selain scene High identik byte-per-byte.
- Header bundle dan nama file internal sama. Tidak ada objek asli yang hilang atau berubah tipe.
- Semua objek asli selain tekstur identik byte-per-byte, termasuk semua material (juga 8 material air). Ada dua
  pengecualian:
  - PreloadData: ditambah 2 shader efek.
  - Cubemap air: diganti versi 128 px (orientasi sama, tidak lebih terang).
- 1284 objek terbaca ulang lewat typetree.
- 73 tekstur ter-decode. Ukuran data cocok dengan format dan mipmap. Isi dan orientasinya berkorelasi dengan
  aslinya, tidak ada yang terbalik.
- Cubemap: ukuran per sisi dan total cocok. Keenam sisinya berisi, dengan orientasi yang sama seperti aslinya.
- Objek yang ditambahkan persis sesuai rencana: 12 sistem efek + 1 root, 3 material, 3 tekstur. Semua referensinya
  valid (komponen, hierarki, material → tekstur dan shader, PreloadData).
- Kapasitas partikel cukup. Total partikel di bawah anggaran 260.

Catatan: validasi ini memeriksa struktur file. Tampilan di dalam game belum bisa saya uji langsung di HP.

## Build ulang dari file asli

```bash
pip install -r tools/requirements.txt
# bobot Real-ESRGAN (resmi, BSD-3) — dimuat tanpa torch, lewat unpickler terbatas (tanpa eksekusi kode)
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth
#   sha256 8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292  realesr-general-x4v3.pth
#   sha256 1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca  realesr-general-wdn-x4v3.pth
python tools/sr_model.py realesr-general-x4v3.pth realesr-general-wdn-x4v3.pth 0.45 sr_dni45.onnx
#   sha256 c203fe1195582e3ae7f95f4d0f8657ccda78baa98a0255103babe41a8f146f37  sr_dni45.onnx
unzip Sanctum_Island_Map.zip -d orig        # -> orig/Scenes/android/...
python tools/build_map.py orig/Scenes/android out/Scenes/android report.json sr_dni45.onnx 4
python tools/validate_map.py orig/Scenes/android out/Scenes/android
python tools/map_previews.py orig/Scenes/android/PVP_049_add.unity3d out/Scenes/android/PVP_049_add.unity3d previews
python tools/pack_like.py Sanctum_Island_Map.zip out Sanctum_Island_Map_HD.zip
```

Build dari nol memakan ±13 menit dengan 4 core. Kalau variabel `MAP_SR_CACHE=<folder>` diisi, hasil AI
disimpan di cache dan build berikutnya ±5 menit, dengan hasil yang identik. Zip-nya (SHA-256
`6aeb40088b4dd457996613efbf2ea9fc28e3ba6f42a82733f2bfd5554a47e5e4`) bisa direproduksi: build ulang dari nol
tanpa cache menghasilkan zip yang identik. Inferensi AI-nya deterministik pada jumlah thread yang sama.

| Tool | Fungsi |
|---|---|
| `sr_model.py` | muat bobot Real-ESRGAN tanpa torch, campur denoise, ekspor ONNX, upscale ×2 per tile |
| `map_hd.py` | pembersihan painterly (Kuwahara), palet premium, kilau ornamen, sharpening tepi, grading (lebih gelap) |
| `map_bake.py` | bayangan bangunan + AO dari geometri, posisi dunia per texel, relief/AO celah/kilau PBR, cubemap air |
| `map_fx.py` + `map_fx_templates.json` | efek ambient baru dan penyisipannya ke scene (template tipe ParticleSystem Unity 2019.4.33f1) |
| `build_map.py` | build lengkap scene High |
| `validate_map.py` | validasi di atas |
| `map_render.py`, `map_previews.py` | render peta tampak atas (dengan props dan foliage alpha-test) dan pratinjau |
| `pack_like.py` | zip dengan entri / urutan / kompresi sama seperti zip asli |
