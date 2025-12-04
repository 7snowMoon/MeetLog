"""MeetLogアイコン生成スクリプト"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_icon():
    # 256x256のアイコンを作成
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 背景 - 落ち着いたダークグレー
    draw.ellipse([10, 10, size-10, size-10], fill='#343a40')
    draw.ellipse([20, 20, size-20, size-20], fill='#212529')
    
    # マイクのアイコン（シンプルな形状）
    mic_color = '#5c7cfa'  # 落ち着いた青
    
    # マイクの頭部（楕円）
    mic_x = size // 2
    mic_top = 55
    mic_width = 45
    mic_height = 70
    draw.ellipse([mic_x - mic_width, mic_top, mic_x + mic_width, mic_top + mic_height], 
                 fill=mic_color)
    
    # マイクの本体（長方形）
    body_top = mic_top + mic_height // 2
    body_height = 50
    draw.rectangle([mic_x - mic_width, body_top, mic_x + mic_width, body_top + body_height],
                   fill=mic_color)
    
    # マイクのスタンド（U字型）
    stand_color = '#868e96'  # グレー
    stand_width = 8
    stand_outer = mic_width + 20
    
    # 左の縦線
    draw.rectangle([mic_x - stand_outer - stand_width//2, body_top + 20,
                    mic_x - stand_outer + stand_width//2, body_top + 70], fill=stand_color)
    # 右の縦線
    draw.rectangle([mic_x + stand_outer - stand_width//2, body_top + 20,
                    mic_x + stand_outer + stand_width//2, body_top + 70], fill=stand_color)
    # 下の横線
    draw.rectangle([mic_x - stand_outer, body_top + 60,
                    mic_x + stand_outer, body_top + 70], fill=stand_color)
    
    # スタンドポール
    pole_width = 10
    draw.rectangle([mic_x - pole_width//2, body_top + 65,
                    mic_x + pole_width//2, body_top + 100], fill=stand_color)
    # ベース
    draw.ellipse([mic_x - 35, body_top + 90, mic_x + 35, body_top + 115], fill=stand_color)
    
    # AIのシンボル（波形/音波）
    wave_color = '#69db7c'  # 柔らかい緑
    wave_y = size - 60
    
    # 3本の波線を描画
    for i, offset in enumerate([-50, 0, 50]):
        x = mic_x + offset
        height = 15 + i * 5 if i <= 1 else 15
        draw.rectangle([x - 4, wave_y - height, x + 4, wave_y + height], fill=wave_color)
    
    # アイコンを保存（複数サイズ）
    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icons = [img.resize(s, Image.Resampling.LANCZOS) for s in icon_sizes]
    
    # ICOファイルとして保存
    ico_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
    icons[5].save(ico_path, format='ICO', sizes=[(s[0], s[1]) for s in icon_sizes])
    
    # PNGも保存（高解像度）
    png_path = os.path.join(os.path.dirname(__file__), 'icon.png')
    img.save(png_path, 'PNG')
    
    print(f"✅ アイコンを作成しました:")
    print(f"   - {ico_path}")
    print(f"   - {png_path}")

if __name__ == "__main__":
    create_icon()
