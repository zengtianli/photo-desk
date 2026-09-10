"""Generate synthetic input images; never access the user's Photos library."""
import datetime as dt
import json
from pathlib import Path
import shutil
import uuid
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/demo-input'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    photos = []
    font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 36)
    small = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 22)
    for i in range(9):
        kind = i // 3
        im = Image.new('RGB', (1200, 800), ['#e8efdf', '#f0e8da', '#eff7f5'][kind])
        d = ImageDraw.Draw(im)
        if kind == 0:
            d.ellipse((760, 90, 930, 260), fill='#efbe6c')
            d.polygon([(0, 640), (300 + i * 20, 240), (650, 640)], fill='#6c9983')
            d.polygon([(300, 670), (820 - i * 30, 300), (1200, 670)], fill='#285e57')
            d.rectangle((0, 650, 1200, 800), fill='#9fbdcc')
            title, albums = 'Weekend / 0' + str(i+1), ['周末散步']
        elif kind == 1:
            x = 420 + (i - 3) * 60
            d.ellipse((x, 270, x+340, 650), fill='#cda46f')
            d.ellipse((x+10, 180, x+330, 480), fill='#dcb982')
            d.polygon([(x+20, 290), (x+10, 95), (x+150, 220)], fill='#dcb982')
            d.polygon([(x+195, 220), (x+330, 95), (x+315, 295)], fill='#dcb982')
            d.ellipse((x+83, 294, x+105, 330), fill='#394f49')
            d.ellipse((x+239, 294, x+261, 330), fill='#394f49')
            d.polygon([(x+160, 350), (x+185, 350), (x+173, 366)], fill='#986555')
            for y in (361, 380):
                d.line((x+40, y, x+137, y+8), fill='#735e47', width=3)
                d.line((x+208, y+8, x+305, y), fill='#735e47', width=3)
            title, albums = 'Cat diary / 0' + str(i-2), ['猫咪日常']
        else:
            d.rounded_rectangle((180, 120, 1020, 700), 18, fill='white')
            d.text((240, 180), 'Design Review Meeting', font=font, fill='#15574f')
            d.text((240, 255), 'Agenda / 2026-09-09', font=font, fill='#15574f')
            d.text((240, 620), f'Sample meeting note {i - 5}', font=small, fill='#748b7f')
            for j, line in enumerate(['1. Review the sample collection', '2. Confirm the next chapter', '3. Plan the next visit']):
                d.text((240, 365 + j*70), line, font=small, fill='#485b55')
            title, albums = 'Design review meeting', ['设计讨论会']
        d.text((50, 35), title, font=font, fill='#284b44')
        d.rounded_rectangle((35, 736, 635, 782), 8, fill='#ffffff')
        d.text((50, 746), 'PhotoDesk synthetic demo / no personal photos', font=small, fill='#41675c')
        name = f'sample-{i+1:02d}.png'
        im.save(OUT / name)
        date = dt.datetime(2026, 9, 7+kind, 10+i%3, tzinfo=dt.timezone(dt.timedelta(hours=8))).isoformat()
        photos.append({'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, f'photodesk-demo/{name}')).upper(),
                       'file': name, 'date': date, 'title': title, 'albums': albums})
    shutil.copyfile(OUT / 'sample-01.png', OUT / 'sample-01-copy.png')
    photos.append(dict(photos[0], file='sample-01-copy.png', uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, 'photodesk-demo/copy')).upper()))
    data = {'format': 'photodesk-synthetic-input-v1', 'description': 'Generated drawings, not real photos or precomputed app output.',
            'license': 'Original PhotoDesk fixtures; permitted for product screenshots and demos.', 'photos': photos}
    (OUT / 'demo-input.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    env = {'PHOTODESK_DEMO_ROOT': str(OUT), 'PHOTODESK_DATA_ROOT': str(OUT / 'state'),
           'PHOTODESK_PREFERENCES_SUITE': 'PhotoDesk.Test.ProductDemo', 'PHOTODESK_BACKGROUND': '1'}
    (OUT / 'environment.json').write_text(json.dumps(env, indent=2) + '\n')
    print(f'Synthetic inputs: {OUT}; 10 images, one exact duplicate. No Photos API was used.')


if __name__ == '__main__':
    main()
