#!/usr/bin/env python3
"""Test script for video processing without Telegram."""
import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.video_processor import process_video, create_text_overlay
from bot.config import TEMP_DIR


def test_text_overlay():
    """Test text overlay generation."""
    print("Testing text overlay generation...")
    
    # Test different sizes
    sizes = [(720, 1280), (1080, 1080), (1280, 720)]
    
    for width, height in sizes:
        output_path = os.path.join(TEMP_DIR, f"test_overlay_{width}x{height}.png")
        try:
            result = create_text_overlay(width, height, "TG: @cododel_dev", output_path)
            print(f"  ✓ Created overlay: {result}")
        except Exception as e:
            print(f"  ✗ Failed for {width}x{height}: {e}")


def test_video_processing(input_video_path: str):
    """Test video processing with FFmpeg."""
    print(f"\nTesting video processing with: {input_video_path}")
    
    if not os.path.exists(input_video_path):
        print(f"  ✗ Input file not found: {input_video_path}")
        return
    
    from bot.config import ASPECT_RATIOS
    
    for ratio, size in ASPECT_RATIOS.items():
        output_path = os.path.join(TEMP_DIR, f"test_output_{ratio}.mp4")
        try:
            print(f"  Processing {ratio} ({size[0]}x{size[1]})...", end=" ")
            process_video(input_video_path, output_path, size)
            print(f"✓ Output: {output_path}")
        except Exception as e:
            print(f"✗ Failed: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("Circle Overlay Bot - Test Suite")
    print("=" * 50)
    
    # Test 1: Text overlay
    test_text_overlay()
    
    # Test 2: Video processing (if sample video provided)
    if len(sys.argv) > 1:
        test_video_processing(sys.argv[1])
    else:
        print("\nSkipping video processing test (no input video provided)")
        print("Usage: python test_processor.py <path_to_video_note.mp4>")
