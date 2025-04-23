from flask import Flask, render_template, request, send_from_directory, redirect, url_for, jsonify
import os, io
import uuid
import time # Import time for cleanup
from rembg import remove
from PIL import Image
import subprocess
import sys # To get the current python executable
import shutil # To find executable path

app = Flask(__name__)
UPLOAD_FOLDER = "processing/input"
OUTPUT_FOLDER = "processing/output"
TEMP_FOLDER = "processing/temp" # Keep temp folder for intermediate files during processing
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
CLEANUP_AGE_SECONDS = 3600 # 1 hour

for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- New Cleanup Function ---
def cleanup_old_files(directory, max_age_seconds):
    """Removes files in the specified directory older than max_age_seconds."""
    now = time.time()
    cleaned_count = 0
    print(f"Running cleanup for directory: {directory}")
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path):
                    file_mtime = os.path.getmtime(file_path)
                    if (now - file_mtime) > max_age_seconds:
                        os.remove(file_path)
                        print(f"Deleted old file: {file_path}")
                        cleaned_count += 1
            except FileNotFoundError:
                print(f"Warning: File not found during cleanup check: {file_path}")
                continue # File might have been deleted by another process
            except OSError as e:
                print(f"Error deleting file {file_path}: {e}")
            except Exception as e:
                 print(f"Unexpected error processing file {file_path} during cleanup: {e}")
    except Exception as e:
        print(f"Error listing directory {directory} for cleanup: {e}")

    if cleaned_count == 0:
        print(f"No old files found to clean in {directory}.")
    else:
        print(f"Cleaned up {cleaned_count} old files from {directory}.")

# --- Refactored Vectorization Logic ---
def vectorize_image(image_path_for_vectorization, base_unique_id, mode, colors, detail, bw_threshold=50):
    """
    Vectorizes the image using potrace or vtracer based on mode.
    Args:
        image_path_for_vectorization (str): Path to the preprocessed image (RGBA PNG for color, RGB PNG for bw).
        base_unique_id (str): The UUID base name for output files.
        mode (str): 'bw' or 'color'.
        colors (int): Number of colors for vtracer (1-32).
        detail (int): Detail level for vtracer (1-10).
        bw_threshold (int): Threshold percentage (0-100) specifically for black & white conversion (potrace).
    Returns:
        str: The filename of the generated SVG, or raises an Exception on error.
    """
    # Generate a new unique ID for this specific vectorization output
    output_unique_id = str(uuid.uuid4())
    svg_filename = f"{base_unique_id}_{output_unique_id}.svg"
    svg_output_path = os.path.join(OUTPUT_FOLDER, svg_filename)
    bw_temp_bmp_path = None # Initialize path for temporary BMP file
    temp_prepped_png_path = None # Initialize path for temp PNG used by vtracer/potrace

    try:
        if mode == 'bw':
            # --- Black & White Vectorization (Potrace) ---
            # 1. Convert the input PNG (already RGB with white bg) to a binary BMP using PIL/Pillow
            bw_temp_bmp_filename = f"{base_unique_id}_{output_unique_id}_bw.bmp"
            bw_temp_bmp_path = os.path.join(TEMP_FOLDER, bw_temp_bmp_filename)
            temp_prepped_png_path = image_path_for_vectorization # Keep track for cleanup
            # Use the specific bw_threshold parameter here
            threshold_percent = max(0, min(100, bw_threshold)) # Clamp threshold 0-100
            threshold_value = int(255 * threshold_percent / 100) # Convert to 0-255 range

            print(f"Preparing BW BMP using PIL: Input={image_path_for_vectorization}, BW Threshold={threshold_percent}% ({threshold_value})")
            try:
                img_rgb = Image.open(image_path_for_vectorization)
                # Convert to grayscale ('L'), then apply threshold to get binary ('1')
                # Pixels > threshold_value become white (255), others black (0)
                # Potrace treats black as foreground, so this mapping is correct.
                img_binary = img_rgb.convert('L').point(lambda x: 255 if x > threshold_value else 0, mode='1')
                img_binary.save(bw_temp_bmp_path, 'BMP')
                del img_rgb, img_binary # Clean up memory
            except Exception as pil_error:
                 print(f"Error during PIL BW conversion: {pil_error}")
                 raise Exception(f"Failed to convert image to BW BMP using PIL: {pil_error}") from pil_error

            # 2. Use Potrace on the generated BMP
            potrace_cmd = ['potrace', bw_temp_bmp_path, '-s', '-o', svg_output_path] # -s for SVG output
            print(f"Running Potrace: {' '.join(potrace_cmd)}")
            subprocess.run(potrace_cmd, check=True)

        else: # mode == 'color'
            # --- Color Vectorization (VTracer) ---
            # Input image (image_path_for_vectorization) is expected to be RGBA PNG
            temp_prepped_png_path = image_path_for_vectorization # Keep track for cleanup

            # Map frontend color slider (2-32) to vtracer's color precision (1-8)
            # Clamp input colors first just in case
            colors_clamped = max(2, min(32, colors))
            # Linear mapping: 2->1, 32->8
            color_precision_val = max(1, min(8, round(1 + (colors_clamped - 2) * (7 / 30))))

            # Map frontend detail slider (1-10) to vtracer's path precision (e.g., 1-8)
            # Higher detail means higher precision (higher value)
            # Clamp input detail first
            detail_clamped = max(1, min(10, detail))
            path_precision_val = max(1, min(8, round(1 + (detail_clamped - 1) * (7 / 9))))

            # Use a fixed value for filter_speckle. Lower value allows smaller details. vtracer default is 4.
            filter_speckle_val = 2 # Reduced from 4 to potentially keep more detail
            # Find the vtracer executable
            vtracer_executable = shutil.which('vtracer')
            if not vtracer_executable:
                raise FileNotFoundError("vtracer command not found in PATH.")

            vtracer_cmd = [
                vtracer_executable,
                '--input', image_path_for_vectorization, # Should be RGBA PNG
                '--output', svg_output_path,
                '--colormode', 'color',
                '--color_precision', str(color_precision_val),
                '--filter_speckle', str(filter_speckle_val), # Use fixed speckle filter
                '--path_precision', str(path_precision_val), # Use detail mapping for path precision
                '--mode', 'spline', # Use splines for smoother curves
            ]
            print(f"Running VTracer CLI: {' '.join(vtracer_cmd)}")
            result = subprocess.run(vtracer_cmd, check=False, capture_output=True, text=True)

            if result.returncode != 0:
                error_message = f"vtracer failed with exit code {result.returncode}."
                if result.stdout: error_message += f"\nStdout:\n{result.stdout}"
                if result.stderr: error_message += f"\nStderr:\n{result.stderr}"
                raise Exception(error_message)


        return svg_filename # Return the name of the generated SVG

    except subprocess.CalledProcessError as e:
         tool_name = 'potrace' if mode == 'bw' else 'vtracer'
         # Include stderr if available
         stderr_output = e.stderr.decode() if e.stderr else 'No stderr output.'
         print(f"Error during vectorization subprocess ({tool_name}): {e}\nStderr: {stderr_output}")
         raise Exception(f"Error during vectorization subprocess ({tool_name}): {e}\nStderr: {stderr_output}") from e
    except FileNotFoundError as e:
         # Determine which tool was actually missing
         if mode == 'color' and 'vtracer' in str(e):
             tool_name = 'vtracer'
             error_msg = f"{tool_name} command not found in PATH. Please install vtracer CLI tool."
         elif mode == 'bw':
             tool_name = 'potrace'
             if 'potrace' in str(e): tool_name = 'potrace'
             error_msg = f"{tool_name} command not found. Is it installed and in PATH?"
         else:
             error_msg = f"An unexpected FileNotFoundError occurred: {e}"
         print(f"Error: {error_msg}")
         raise Exception(error_msg) from e
    except Exception as e: # Catch other potential errors
         print(f"Error during vectorization: {e}")
         raise Exception(f"Error during vectorization: {e}") from e
    finally:
        # Clean up temporary files used by vectorizers
        if bw_temp_bmp_path and os.path.exists(bw_temp_bmp_path):
            try: os.remove(bw_temp_bmp_path)
            except OSError as e: print(f"Warning: Could not remove temp file {bw_temp_bmp_path}: {e}")
        # Also remove the prepped PNG that was input to the vectorizer
        if temp_prepped_png_path and os.path.exists(temp_prepped_png_path):
             try: os.remove(temp_prepped_png_path)
             except OSError as e: print(f"Warning: Could not remove temp prepped file {temp_prepped_png_path}: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # --- Run Cleanup ---
        try:
            cleanup_old_files(UPLOAD_FOLDER, CLEANUP_AGE_SECONDS)
            cleanup_old_files(OUTPUT_FOLDER, CLEANUP_AGE_SECONDS)
            # Optionally clean TEMP_FOLDER too, though vectorizer should clean its own temps
            cleanup_old_files(TEMP_FOLDER, CLEANUP_AGE_SECONDS)
        except Exception as cleanup_error:
            print(f"Warning: Initial cleanup failed: {cleanup_error}")

        # Check if the post request has the file part
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files['file']
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Get parameters from the form data
        mode = request.form.get('mode', 'color') # Default to color now
        try:
            # Colors (2-32 from frontend)
            colors = int(request.form.get('colors', 8)) # Default from frontend is 8
        except (ValueError, TypeError):
            colors = 8
        colors = max(2, min(32, colors)) # Clamp to frontend range

        try:
            # Detail (1-10 from frontend)
            detail = int(request.form.get('detail', 5)) # Default from frontend is 5
        except (ValueError, TypeError):
            detail = 5
        detail = max(1, min(10, detail)) # Clamp to frontend range

        # Read the correct threshold based on mode (although only BW uses it currently)
        # We still read it here to pass it correctly if mode is BW
        current_mode = request.form.get('mode', 'bw') # Get mode again to decide which threshold to read
        bw_threshold_value_str = '50' # Default BW threshold
        color_threshold_value_str = '20' # Default Color threshold

        if current_mode == 'bw':
            bw_threshold_value_str = request.form.get('bg_threshold_bw', '50')
        else: # color mode
            color_threshold_value_str = request.form.get('bg_threshold_col', '20')

        try:
            bw_threshold_for_vectorize = int(bw_threshold_value_str)
        except (ValueError, TypeError):
             bw_threshold_for_vectorize = 50
        bw_threshold_for_vectorize = max(0, min(100, bw_threshold_for_vectorize)) # Clamp BW threshold

        try:
            color_threshold_for_rembg = int(color_threshold_value_str)
        except (ValueError, TypeError):
            color_threshold_for_rembg = 20
        color_threshold_for_rembg = max(0, min(100, color_threshold_for_rembg)) # Clamp Color threshold

        # Remove Background flag (boolean from frontend)
        # The value from checkbox is 'on' if checked, otherwise missing. Convert to boolean.
        remove_background = request.form.get('remove_bg') == 'on' # True if checked, False otherwise

        if file and allowed_file(file.filename):
            # --- Initial Upload Processing ---
            original_extension = file.filename.rsplit('.', 1)[1].lower()
            unique_id = str(uuid.uuid4())
            input_filename = f"{unique_id}.{original_extension}" # Store this original filename
            input_path = os.path.join(UPLOAD_FOLDER, input_filename)
            file.save(input_path)
            temp_image_for_vectorization_path = None # Path for the image passed to vectorize_image

            try:
                # --- Prepare Image for Vectorization (Mode-Dependent) ---
                print(f"Initial Upload: Processing for mode='{mode}', remove_bg={remove_background}")
                img_original = Image.open(input_path)
                image_to_process = img_original.copy() # Work on a copy

                if remove_background:
                    print("Initial Upload: Removing background...")
                    img_byte_arr = io.BytesIO()
                    img_format = image_to_process.format if image_to_process.format else 'PNG'
                    if img_format.upper() == 'JPEG': img_format = 'PNG'
                    image_to_process.save(img_byte_arr, format=img_format)
                    img_byte_arr.seek(0)
                    try:
                        rembg_params = { # Default params
                            "alpha_matting": True,
                            "alpha_matting_foreground_threshold": 235,
                            "alpha_matting_background_threshold": 15,
                            "alpha_matting_erode_size": 1
                        }
                        if mode == 'color':
                            # Map slider 0-100 to rembg thresholds for color mode (non-linear scaling)
                            # Slider 0 (vorsichtig): fg=250, bg=10
                            # Slider 100 (aggressiv): fg=225, bg=35
                            # Use cubic scaling for finer control at low values, even more aggressive at high values
                            normalized_slider = color_threshold_for_rembg / 100.0
                            scaled_slider = normalized_slider ** 3 # Cubic scaling
                            fg_thresh = round(250 - scaled_slider * 25) # Range 250 -> 225
                            bg_thresh = round(10 + scaled_slider * 25) # Range 10 -> 35
                            rembg_params["alpha_matting_foreground_threshold"] = fg_thresh
                            rembg_params["alpha_matting_background_threshold"] = bg_thresh
                            print(f"Initial Upload: Using color threshold {color_threshold_for_rembg} (scaled: {scaled_slider:.2f}) -> rembg fg={fg_thresh}, bg={bg_thresh}")
                        else:
                             print(f"Initial Upload: Using default rembg params for mode '{mode}'")


                        output_data_bytes = remove(img_byte_arr.read(), **rembg_params)
                        image_after_rembg = Image.open(io.BytesIO(output_data_bytes))
                        # Ensure RGBA after rembg
                        if image_after_rembg.mode != 'RGBA':
                            image_after_rembg = image_after_rembg.convert('RGBA')
                        image_to_process = image_after_rembg
                    except Exception as rembg_error:
                         print(f"rembg failed during initial upload: {rembg_error}. Proceeding without background removal.")
                         # Fallback: ensure the original image is RGBA if we intended to remove bg
                         if image_to_process.mode != 'RGBA':
                              image_to_process = image_to_process.convert('RGBA')
                    finally:
                         del img_byte_arr

                # --- Mode-specific preparation ---
                temp_filename_base = f"{unique_id}_prepped"
                if mode == 'color':
                    # For color mode, ensure RGBA and save as PNG
                    print("Initial Upload: Preparing for color mode (RGBA PNG)...")
                    if image_to_process.mode != 'RGBA':
                        image_to_process = image_to_process.convert('RGBA')
                    temp_image_filename = f"{temp_filename_base}.png"
                    temp_image_for_vectorization_path = os.path.join(TEMP_FOLDER, temp_image_filename)
                    image_to_process.save(temp_image_for_vectorization_path, 'PNG')
                else: # mode == 'bw'
                    # For bw mode, place on white background, convert to RGB, save as PNG
                    # (vectorize_image will handle the conversion to BMP + threshold)
                    print("Initial Upload: Preparing for bw mode (RGB PNG on white bg)...")
                    white_bg = Image.new("RGBA", image_to_process.size, "WHITE")
                    # Ensure image_to_process is RGBA before pasting if it has alpha
                    if image_to_process.mode != 'RGBA':
                         image_to_process = image_to_process.convert('RGBA')
                    white_bg.paste(image_to_process, (0, 0), image_to_process) # Use alpha mask
                    final_rgb = white_bg.convert("RGB")
                    temp_image_filename = f"{temp_filename_base}.png"
                    temp_image_for_vectorization_path = os.path.join(TEMP_FOLDER, temp_image_filename)
                    final_rgb.save(temp_image_for_vectorization_path, 'PNG')
                    del final_rgb # Clean up memory

                del image_to_process # Clean up memory

                # --- Vectorization ---
                print(f"Initial Upload: Calling vectorize_image with path: {temp_image_for_vectorization_path}")
                # Note: vectorize_image now handles cleanup of its temp input file (temp_image_for_vectorization_path)
                svg_filename = vectorize_image(
                    image_path_for_vectorization=temp_image_for_vectorization_path,
                    base_unique_id=unique_id,
                    mode=mode,
                    colors=colors,
                    detail=detail,
                    bw_threshold=bw_threshold_for_vectorize # Pass only the BW threshold
                )

            except Exception as e:
                 print(f"Error during initial processing: {e}")
                 # No need to clean temp_image_for_vectorization_path here, vectorize_image's finally block handles it
                 return jsonify({"error": f"Processing failed: {e}"}), 500
            # No finally block needed here for temp_image_for_vectorization_path cleanup


            # Return JSON for AJAX requests (Initial Upload)
            return jsonify({
                "uploaded_file_url": url_for('uploaded_file_serve', filename=input_filename), # URL of original upload
                "input_filename": input_filename, # Pass back the original filename for reprocess
                "svg_file_url": url_for('serve_svg', filename=svg_filename), # URL of the generated SVG
                "download_url": url_for('download_file', filename=svg_filename) # Download URL for this SVG
            })
        elif file:
             return jsonify({"error": "File type not allowed"}), 400
        else: # Should not happen if file checks are done correctly, but as a fallback
             return jsonify({"error": "Invalid state"}), 400

    # For GET requests, just render the initial page
    return render_template('index.html')


# --- New Route for Reprocessing ---
@app.route('/reprocess', methods=['POST'])
def reprocess():
    # --- Run Cleanup ---
    try:
        cleanup_old_files(UPLOAD_FOLDER, CLEANUP_AGE_SECONDS)
        cleanup_old_files(OUTPUT_FOLDER, CLEANUP_AGE_SECONDS)
        cleanup_old_files(TEMP_FOLDER, CLEANUP_AGE_SECONDS)
    except Exception as cleanup_error:
        print(f"Warning: Reprocess cleanup failed: {cleanup_error}")

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    input_filename = data.get('input_filename')
    mode = data.get('mode', 'color') # Default to color
    try:
        # Colors (2-32 from frontend)
        colors = int(data.get('colors', 8))
    except (ValueError, TypeError):
        colors = 8
    colors = max(2, min(32, colors))

    try:
        # Detail (1-10 from frontend)
        detail = int(data.get('detail', 5))
    except (ValueError, TypeError):
        detail = 5
    detail = max(1, min(10, detail))

    # Read the correct threshold based on mode from JSON data
    current_mode_reprocess = data.get('mode', 'bw')
    # Frontend sends the correct threshold value under 'bg_threshold' key
    threshold_value_reprocess = data.get('bg_threshold', 50 if current_mode_reprocess == 'bw' else 20) # Default based on mode

    bw_threshold_for_vectorize_reprocess = 50
    color_threshold_for_rembg_reprocess = 20

    try:
        if current_mode_reprocess == 'bw':
            bw_threshold_for_vectorize_reprocess = int(threshold_value_reprocess)
        else: # color mode
            color_threshold_for_rembg_reprocess = int(threshold_value_reprocess)
    except (ValueError, TypeError):
        # Keep defaults if conversion fails
        pass

    # Clamp values
    bw_threshold_for_vectorize_reprocess = max(0, min(100, bw_threshold_for_vectorize_reprocess))
    color_threshold_for_rembg_reprocess = max(0, min(100, color_threshold_for_rembg_reprocess))

    # Get remove background flag (boolean from frontend)
    remove_background = data.get('remove_bg', True) # Sent as boolean from frontend JS

    if not input_filename:
        return jsonify({"error": "Missing input filename"}), 400

    # Security check: ensure filename is safe
    if '..' in input_filename or input_filename.startswith('/'):
         return jsonify({"error": "Invalid input filename"}), 400
    original_input_path = os.path.join(UPLOAD_FOLDER, input_filename)

    if not os.path.exists(original_input_path):
         return jsonify({"error": "Original input file not found"}), 404

    base_unique_id = input_filename.split('.')[0] # Get the original UUID part
    temp_image_for_vectorization_path = None # Path for the image passed to vectorize_image
    reprocess_unique_id = str(uuid.uuid4()) # Unique ID for temp files in this reprocess request

    try:
        # --- Prepare Image for Vectorization (Mode-Dependent) ---
        print(f"Reprocessing: Processing for mode='{mode}', remove_bg={remove_background}")
        img_original = Image.open(original_input_path)
        image_to_process = img_original.copy() # Work on a copy

        if remove_background:
            print("Reprocessing: Removing background...")
            img_byte_arr = io.BytesIO()
            img_format = image_to_process.format if image_to_process.format else 'PNG'
            if img_format.upper() == 'JPEG': img_format = 'PNG'
            image_to_process.save(img_byte_arr, format=img_format)
            img_byte_arr.seek(0)
            try:
                rembg_params_reprocess = { # Default params
                    "alpha_matting": True,
                    "alpha_matting_foreground_threshold": 235,
                    "alpha_matting_background_threshold": 15,
                    "alpha_matting_erode_size": 1
                }
                if mode == 'color':
                    # Map slider 0-100 to rembg thresholds for color mode (non-linear scaling)
                   # Slider 0 (vorsichtig): fg=250, bg=10
                   # Slider 100 (aggressiv): fg=225, bg=35
                   # Use cubic scaling for finer control at low values, even more aggressive at high values
                   normalized_slider_reprocess = color_threshold_for_rembg_reprocess / 100.0
                   scaled_slider_reprocess = normalized_slider_reprocess ** 3 # Cubic scaling
                   fg_thresh_reprocess = round(250 - scaled_slider_reprocess * 25) # Range 250 -> 225
                   bg_thresh_reprocess = round(10 + scaled_slider_reprocess * 25) # Range 10 -> 35
                   rembg_params_reprocess["alpha_matting_foreground_threshold"] = fg_thresh_reprocess
                   rembg_params_reprocess["alpha_matting_background_threshold"] = bg_thresh_reprocess # Corrected indentation
                   print(f"Reprocessing: Using color threshold {color_threshold_for_rembg_reprocess} (cubic scaled: {scaled_slider_reprocess:.2f}) -> rembg fg={fg_thresh_reprocess}, bg={bg_thresh_reprocess}") # Updated print
                else:
                    print(f"Reprocessing: Using default rembg params for mode '{mode}'")

                output_data_bytes = remove(img_byte_arr.read(), **rembg_params_reprocess)
                image_after_rembg = Image.open(io.BytesIO(output_data_bytes))
                 # Ensure RGBA after rembg
                if image_after_rembg.mode != 'RGBA':
                    image_after_rembg = image_after_rembg.convert('RGBA')
                image_to_process = image_after_rembg
            except Exception as rembg_error:
                 print(f"rembg failed during reprocess: {rembg_error}. Proceeding without background removal.")
                 # Fallback: ensure the original image is RGBA if we intended to remove bg
                 if image_to_process.mode != 'RGBA':
                      image_to_process = image_to_process.convert('RGBA')
            finally:
                 del img_byte_arr
        else:
             # If not removing background, ensure it's RGBA for color mode consistency
             if mode == 'color' and image_to_process.mode != 'RGBA':
                  print("Reprocessing: Converting original to RGBA for color mode (no bg removal)...")
                  image_to_process = image_to_process.convert('RGBA')
             # For BW mode without removal, it will be handled below

        # --- Mode-specific preparation ---
        temp_filename_base = f"{base_unique_id}_{reprocess_unique_id}_prepped"
        if mode == 'color':
            # For color mode, ensure RGBA and save as PNG
            print("Reprocessing: Preparing for color mode (RGBA PNG)...")
            if image_to_process.mode != 'RGBA': # Double check, might have been converted already
                image_to_process = image_to_process.convert('RGBA')
            temp_image_filename = f"{temp_filename_base}.png"
            temp_image_for_vectorization_path = os.path.join(TEMP_FOLDER, temp_image_filename)
            image_to_process.save(temp_image_for_vectorization_path, 'PNG')
        else: # mode == 'bw'
            # For bw mode, place on white background, convert to RGB, save as PNG
            print("Reprocessing: Preparing for bw mode (RGB PNG on white bg)...")
            white_bg = Image.new("RGBA", image_to_process.size, "WHITE")
            # Ensure image_to_process is RGBA before pasting if it has alpha
            if image_to_process.mode != 'RGBA':
                 image_to_process = image_to_process.convert('RGBA')
            white_bg.paste(image_to_process, (0, 0), image_to_process) # Use alpha mask
            final_rgb = white_bg.convert("RGB")
            temp_image_filename = f"{temp_filename_base}.png"
            temp_image_for_vectorization_path = os.path.join(TEMP_FOLDER, temp_image_filename)
            final_rgb.save(temp_image_for_vectorization_path, 'PNG')
            del final_rgb

        del image_to_process # Clean up memory

        # --- Vectorization ---
        print(f"Reprocessing: Calling vectorize_image with path: {temp_image_for_vectorization_path}")
        # Note: vectorize_image now handles cleanup of its temp input file (temp_image_for_vectorization_path)
        svg_filename = vectorize_image(
            image_path_for_vectorization=temp_image_for_vectorization_path,
            base_unique_id=base_unique_id,
            mode=mode,
            colors=colors,
            detail=detail,
            bw_threshold=bw_threshold_for_vectorize_reprocess # Pass only the BW threshold
        )

        # --- Return new SVG details ---
        return jsonify({
            "svg_file_url": url_for('serve_svg', filename=svg_filename),
            "download_url": url_for('download_file', filename=svg_filename)
        })

    except Exception as e:
        print(f"Error during reprocessing: {e}")
        # No need to clean temp_image_for_vectorization_path here, vectorize_image's finally block handles it
        return jsonify({"error": f"Reprocessing failed: {e}"}), 500
    # No finally block needed here for temp_image_for_vectorization_path cleanup


@app.route('/download/<filename>')
def download_file(filename):
    # Basic security check: prevent directory traversal
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400
    return send_from_directory(OUTPUT_FOLDER, filename, as_attachment=True)

# Removed the old /clean route as cleanup is now automatic

# Route to serve uploaded files (original images)
@app.route('/uploads/<filename>')
def uploaded_file_serve(filename):
    # Basic security check: prevent directory traversal
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400
    return send_from_directory(UPLOAD_FOLDER, filename)

# Route to serve generated SVG files
@app.route('/output/<filename>')
def serve_svg(filename):
     # Basic security check: prevent directory traversal
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400
    return send_from_directory(OUTPUT_FOLDER, filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
