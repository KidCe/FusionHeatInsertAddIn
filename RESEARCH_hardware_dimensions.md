# Hardware dimension research

Research date: 2026-08-22

This document records the manufacturer dimensions used to extend the editable
hardware library. The attached package photos were treated as reference
material; the RUTHEX product pages and their official dimension table are the
authoritative sources for the values below.

## RUTHEX metric thread inserts

RUTHEX publishes one official metric size table on its product pages. In that
table:

- `d1` is the maximum outside diameter at the top of the insert;
- `d2` is the smaller outside diameter at the lower shoulder;
- `d3` is the recommended plastic hole diameter;
- `L` is the insert length; and
- `W` is the minimum surrounding wall thickness shown in the diagram.

The recommended blind-hole depth shown by RUTHEX is `L + 1 mm`. Values are in
millimetres. “Short” and “VORON” are separate product geometries, not merely
alternate labels for the standard insert.

| RUTHEX variant | d1 | d2 | d3 / plastic hole | L | W | Product page |
|---|---:|---:|---:|---:|---:|---|
| RX-M2x4 | 3.6 | 3.1 | 3.2 | 4.0 | 1.3 | [M2 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m2-70-stuck-rx-m2x4-messing-gewindebuchsen) |
| RX-M2.5x5.7 | 4.6 | 3.9 | 4.0 | 5.7 | 1.6 | [M2.5 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m2-5-70-stuck-rx-m2-5x5-7-messing-gewindebuchsen) |
| RX-M3Sx4.0 Short | 4.6 | 3.9 | 4.0 | 4.0 | 1.6 | [M3 Short product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m3s-100stuck-rx-m3x4-0-short-messing-gewindebuchsen-fur-3d-druck) |
| RX-M3x5x4 VORON | 5.0 | 4.25 | 4.4 | 4.0 | 1.3 | [M3 VORON product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m3-100-stuck-made-for-voron-rx-m3x5x4-messing-gewindebuchsen-fur-3d-druck) |
| RX-M3x5.7 | 4.6 | 3.9 | 4.0 | 5.7 | 1.6 | [M3 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m3-100-stuck-rx-m3x5-7-messing-gewindebuchsen) |
| RX-M4Sx4.0 Short | 6.3 | 5.5 | 5.6 | 4.0 | 2.1 | [M4 Short product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m4s-50-stuck-rx-m4x4-0-short-messing-gewindebuchsen-fur-3d-druck) |
| RX-M4x8.1 | 6.3 | 5.5 | 5.6 | 8.1 | 2.1 | [M4 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m4-50-stuck-rx-m4x8-1-messing-gewindebuchsen) |
| RX-M5Sx5.8 Short | 7.1 | 6.3 | 6.4 | 5.8 | 2.6 | [M5 Short product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m5s-50-stuck-rx-m5sx5-8-short-messing-gewindebuchsen-fur-3d-druck) |
| RX-M5x9.5 | 7.1 | 6.3 | 6.4 | 9.5 | 2.6 | [M5 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m5-50-stuck-rx-m5x9-5-messing-gewindebuchsen) |
| RX-M6x6.8 Short | 8.7 | 7.9 | 8.0 | 6.8 | 3.3 | [M6 Short product page](https://www.ruthex.de/en/products/ruthex-m6-gewindeeinsatz-short-25-stuck-rx-m6x6-8-gewindebuchsen-aus-messing-stabile-einpressmutter-fur-kunststoffteile-durch-warme-in-3d-druck-teile-aus-kunststoff-einsetzbar) |
| RX-M6x12.7 | 8.7 | 7.9 | 8.0 | 12.7 | 3.3 | [M6 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m6-25-stuck-rx-m6x12-7-messing-gewindebuchsen-fur-3d-druck) |
| RX-M8x12.7 | 10.1 | 9.5 | 9.6 | 12.7 | 4.5 | [M8 product page](https://www.ruthex.de/en/products/ruthex-gewindeeinsatz-m8-20-stuck-rx-m8x12-7-messing-gewindebuchsen) |
| RX-M10x12.7 | 12.6 | 11.8 | 12.0 | 12.7 | 6.0 | [M10 product page](https://www.ruthex.de/en/products/ruthex-10-gewindeeinsatz-10-stuck-ge-m10x127-001) |

The product collection lists these products as part of the [RUTHEX Metric
thread inserts collection](https://www.ruthex.de/en/collections/gewindeeinsatze).
The underlying official size table is also available as the [RUTHEX size-table
image](https://www.ruthex.de/cdn/shop/files/1Tabelle.PT05_eb2a30fa-5c34-46f8-b557-a6c432354560_1600x.jpg?v=1748341911).

### Plugin mapping

The JSON library includes RUTHEX profiles for M2, M3, M4 and M6, including
their Short and VORON variants where offered. M2.5, M5, M8 and M10 remain
documented here until matching screw profiles and a complete UI workflow are
defined.

The RUTHEX `d2` and `W` values are retained in the profile notes because the
current Fusion feature recipe needs the recommended plastic hole (`d3`), the
outer lead-in diameter (`d1`) and the blind-hole depth. It does not currently
model the lower shoulder as a separate stepped feature.

## Screw head dimensions and pocket clearance

The profile library covers Button Head and Socket Cap Head screws for M2, M3,
M4 and M6. The nominal head envelopes are:

| Thread | Button head diameter / height | Socket cap diameter / height | Library head-pocket diameter |
|---|---:|---:|---:|
| M2 | 3.5 / 1.3 | 3.8 / 2.0 | 4.0 / 4.2 |
| M3 | 5.7 / 1.65 | 5.5 / 3.0 | 6.1 / 5.9 |
| M4 | 7.6 / 2.20 | 7.0 / 4.0 | 8.0 / 7.4 |
| M6 | 10.5 / 3.30 | 10.0 / 6.0 | 10.9 / 10.4 |

The library values use a +0.40 mm diametral head clearance (+0.20 mm radial).
The small M2 button-head pocket uses +0.50 mm as a more forgiving starter
value. These are engineering starting values, not ISO dimensions; verify them
with the actual screw supplier and a print coupon.

Sources:

- [ISO 7380-1:2022](https://www.iso.org/standard/78699.html) is the official
  button-head standard record. The standard range starts at M3; M2 is therefore
  represented as a manufacturer-specific similar geometry.
- [Bossard BN 19](https://www.bossard.com/global-en/eshop/screws-and-bolts-with-internal-drive/hex-socket-button-head-cap-screws-partially-fully-threaded/p/19/)
  and its [M2 product data sheet](https://xonstorage.z8.web.core.windows.net/pdf/bossard_1805681_xonlink.pdf)
  document the M2 similar button-head geometry.
- [Böllhoff ISO 7380-1 data sheet](https://eshop-ro.boellhoff.com/out/media/pdf/ISO_7380-1_Stahl_10.9_Innensechskant___en.pdf)
  documents the M3/M4/M6 button-head dimensions.
- [ISO 4762](https://www.iso.org/standard/34460.html) is the official
  socket-head-cap standard record.
- [Böllhoff DIN 912 / ISO 4762 data sheet](https://eshop.boellhoff.de/out/media/pdf/DIN_912_Edelstahl_A4___en.pdf)
  documents the M2/M3/M4/M6 socket-cap dimensions.

The separate shaft through-hole values in the JSON are practical starting
values aligned with common ISO 273 medium-clearance practice. They are not
intended to replace the selected screw supplier's drawing.

## Insert-hole tolerance

The **Insert Hole Diameter Tolerance** dropdown adds a positive amount to the
profile's recommended plastic hole diameter. Available choices are 0.00, 0.05,
0.10, 0.15 and 0.20 mm. For example, the RUTHEX M3 value of 4.00 mm becomes
4.05 or 4.10 mm when selected.

This adjustment is deliberately separate from slicer compensation. It only
changes the Fusion insert-hole diameter; it does not change the lead-in,
insert depth, screw clearance or head pocket. Printer-, material- and
orientation-dependent hole shrinkage must still be calibrated in the slicer or
with a test coupon.
