document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('fileInput');
    const originalPreview = document.getElementById('original-preview');
    const vectorizedPreview = document.getElementById('vectorized-preview');
    const originalPreviewContainer = document.getElementById('original-preview-container');
    const vectorizedPreviewContainer = document.getElementById('vectorized-preview-container');
    const uploadSpinner = document.getElementById('upload-spinner');
    const errorMessage = document.getElementById('error-message');
    const bgThresholdLabel = document.getElementById('bg-threshold-label'); // Added label reference
    const bgThresholdInput = document.getElementById('bg-threshold-input'); // Existing slider reference
    const bgThresholdValue = document.getElementById('bg-threshold-value'); // Existing value span reference
    const removeBgCheckbox = document.getElementById('remove-bg-checkbox'); // Existing checkbox reference
    const modeRadios = document.querySelectorAll('input[name="mode"]'); // Existing mode radios reference
    const colorsControl = document.getElementById('colors-control'); // Existing colors control
    const colorsInputContainer = document.getElementById('colors-input-container'); // Existing colors input container
    const bgThresholdControl = document.getElementById('bg-threshold-control'); // Existing threshold control container div
    const bgThresholdInputContainer = document.getElementById('bg-threshold-input-container'); // Existing threshold input container div

    // --- Drag & Drop Event Listeners ---
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault(); // Prevent default browser behavior
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            fileInput.files = files; // Assign dropped files to the hidden input
            handleFileSelect(files[0]);
        }
    });

    // --- File Input Change Listener ---
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    // --- Trigger File Input Click ---
    dropZone.addEventListener('click', () => {
        fileInput.click(); // Trigger the hidden file input
    });

    // --- Handle File Selection and Preview ---
    let currentFile = null; // Store the currently selected file
    let currentInputFilename = null; // Store the filename of the uploaded original image for reprocessing
    let originalPanzoomInstance = null; // Store panzoom instance for original

    function handleFileSelect(file) {
        if (!file.type.startsWith('image/')) {
            showError('Bitte wählen Sie eine Bilddatei aus.');
            return;
        }
        currentFile = file;
        errorMessage.style.display = 'none'; // Hide previous errors
        vectorizedPreview.innerHTML = ''; // Clear previous vector result
        vectorizedPreviewContainer.classList.remove('checkerboard-bg'); // Remove checkerboard from vector preview

        // Destroy previous panzoom instance if exists
        if (originalPanzoomInstance) {
            originalPanzoomInstance.destroy();
            originalPanzoomInstance = null;
        }

        const reader = new FileReader();
        reader.onload = function(e) {
            originalPreview.innerHTML = `<img src="${e.target.result}" alt="Original Vorschau" id="original-image">`;
            originalPreviewContainer.classList.add('checkerboard-bg'); // Add checkerboard to original preview

            // Initialize Panzoom for the original image
            const imgElement = document.getElementById('original-image');
            if (imgElement) {
                originalPanzoomInstance = Panzoom(imgElement, {
                    maxScale: 5,
                    minScale: 0.5,
                    contain: 'inside'
                });
                // Enable zooming with mouse wheel
                originalPreviewContainer.addEventListener('wheel', (event) => {
                    if (!event.shiftKey) { // Zoom only if Shift key is not pressed (allows normal page scroll)
                       originalPanzoomInstance.zoomWithWheel(event);
                    }
                });
            }
            // Automatically trigger upload after preview
            uploadFile();
        }
        reader.readAsDataURL(file);
    }
// --- Upload File Function ---
let vectorizedSvgPanZoomInstance = null; // Store svg-pan-zoom instance for vectorized SVG
let reprocessTimer = null; // Timer for debouncing reprocess calls


    async function uploadFile() {
        if (!currentFile) {
            showError('Keine Datei zum Hochladen ausgewählt.');
            return;
        }

        // Show spinner and hide previous results/errors
        uploadSpinner.style.display = 'block';
        vectorizedPreview.innerHTML = '';
        vectorizedPreviewContainer.classList.remove('checkerboard-bg');
        errorMessage.style.display = 'none';

        // Destroy previous svg-pan-zoom instance if exists
        if (vectorizedSvgPanZoomInstance) {
            vectorizedSvgPanZoomInstance.destroy();
            vectorizedSvgPanZoomInstance = null;
        }

        // Get parameter values from the form using correct IDs from index.html
        const colorCount = document.getElementById('colors-input').value; // Correct ID
        // const backgroundColor = document.getElementById('backgroundColor').value; // Background color is client-side only for preview
        // const scaleFactor = document.getElementById('scaleFactor').value; // Scale factor removed from backend
        const simplifyTolerance = document.getElementById('detail-input').value; // Correct ID (Detail slider maps to simplifyTolerance)
        const mode = document.querySelector('input[name="mode"]:checked')?.value || 'color'; // Get selected mode
        const threshold = document.getElementById('bg-threshold-input').value; // Correct ID
        const removeBackground = document.getElementById('remove-bg-checkbox').checked; // Correct ID

        const formData = new FormData();
        formData.append('file', currentFile); // Changed 'image' to 'file' to match Flask backend
        formData.append('mode', mode);
        formData.append('color_count', colorCount);
        // formData.append('background_color', backgroundColor); // Not sent
        // formData.append('scale_factor', scaleFactor); // Not sent
        formData.append('simplify_tolerance', simplifyTolerance); // Backend expects simplify_tolerance
        formData.append('threshold', threshold); // Send initial threshold
        formData.append('remove_background', removeBackground); // Send initial background removal state

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData,
            });

            uploadSpinner.style.display = 'none'; // Hide spinner

            if (response.ok) {
                const resultData = await response.json(); // Expect JSON now
                currentInputFilename = resultData.input_filename; // Store the original filename

                // Fetch the actual SVG content from the provided URL
                const svgResponse = await fetch(resultData.svg_file_url);
                if (!svgResponse.ok) {
                    throw new Error(`Failed to fetch SVG: ${svgResponse.statusText}`);
                }
                const svgContent = await svgResponse.text();

                updateVectorizedPreview(svgContent); // Use helper function

                // Update download link
                const downloadLink = document.getElementById('download-link');
                if(downloadLink) {
                    downloadLink.href = resultData.download_url;
                    downloadLink.style.display = 'inline-block'; // Show link
                }


            } else {
                const errorData = await response.json();
                showError(`Fehler beim Hochladen: ${errorData.error || response.statusText}`);
                currentInputFilename = null; // Reset filename on error
                 // Hide download link on error
                const downloadLink = document.getElementById('download-link');
                if(downloadLink) downloadLink.style.display = 'none';
            }
        } catch (error) {
            uploadSpinner.style.display = 'none'; // Hide spinner
            showError(`Fehler: ${error.message}`);
            console.error('Upload/Fetch Error:', error);
            currentInputFilename = null; // Reset filename on error
             // Hide download link on error
            const downloadLink = document.getElementById('download-link');
            if(downloadLink) downloadLink.style.display = 'none';
        }
    }

    // --- Helper Function to Update Vectorized Preview and Initialize svg-pan-zoom ---
    function updateVectorizedPreview(svgContent) {
        vectorizedPreview.innerHTML = svgContent; // Display SVG
        vectorizedPreviewContainer.classList.add('checkerboard-bg'); // Add checkerboard

        // Destroy previous svg-pan-zoom instance if exists
        if (vectorizedSvgPanZoomInstance) {
            vectorizedSvgPanZoomInstance.destroy();
            vectorizedSvgPanZoomInstance = null;
        }

        const svgElement = vectorizedPreview.querySelector('svg'); // Get the SVG element
        if (svgElement && typeof svgPanZoom !== 'undefined') { // Check if svgPanZoom is loaded
            // Ensure the SVG has an ID for svg-pan-zoom to target
            if (!svgElement.id) {
                svgElement.id = 'vectorized-svg-element'; // Assign a unique ID
            }

            // Initialize svg-pan-zoom
            vectorizedSvgPanZoomInstance = svgPanZoom(`#${svgElement.id}`, {
                zoomEnabled: true,
                panEnabled: true,
                controlIconsEnabled: false, // Hide default zoom icons if desired
                fit: true,       // Fit SVG into container initially
                center: true,    // Center SVG in container initially
                minZoom: 0.1,
                maxZoom: 10,
                contain: true    // Contain pan within bounds
            });

            // Optional: Resize and center after a short delay to ensure proper rendering
            setTimeout(() => {
                if (vectorizedSvgPanZoomInstance) {
                    vectorizedSvgPanZoomInstance.resize();
                    vectorizedSvgPanZoomInstance.center();
                    vectorizedSvgPanZoomInstance.fit(); // Ensure it fits after potential resize
                }
            }, 100); // Adjust delay if needed

        } else if (!svgElement) {
             console.error("SVG element not found after update.");
        } else {
            console.error("svgPanZoom library not loaded.");
            showError("Fehler beim Initialisieren der Zoom-Funktion für SVG.");
        }
    }

    // Note: The wheel zoom handler function (vectorizedWheelZoomHandler) is no longer needed
    // as svg-pan-zoom handles wheel events internally.



    // --- Show Error Message ---
    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        uploadSpinner.style.display = 'none'; // Hide spinner on error
    }

    // --- Function to Update Threshold Control Appearance and Behavior ---
    function updateThresholdControl() {
        const isColorMode = document.getElementById('mode-color').checked;
        const isRemoveBgChecked = removeBgCheckbox.checked;

        // Set slider range (always 0-255 now)
        bgThresholdInput.min = "0";
        bgThresholdInput.max = "255";
        // Keep current value if possible, otherwise clamp (though range is same now)
        // bgThresholdInput.value = Math.max(0, Math.min(255, parseInt(bgThresholdInput.value)));

        if (isColorMode) {
            // Color Mode
            bgThresholdLabel.textContent = "Threshold (Farbe):";
            // Show threshold only if remove background is checked
            const showThreshold = isRemoveBgChecked;
            bgThresholdControl.style.display = showThreshold ? 'inline-block' : 'none';
            bgThresholdInputContainer.style.display = showThreshold ? 'inline-block' : 'none';
            // Show color slider
            colorsControl.style.display = 'inline-block';
            colorsInputContainer.style.display = 'inline-block';
        } else {
            // BW Mode
            bgThresholdLabel.textContent = "Threshold (SW):";
            // Always show threshold slider in BW mode
            bgThresholdControl.style.display = 'inline-block';
            bgThresholdInputContainer.style.display = 'inline-block';
            // Hide color slider
            colorsControl.style.display = 'none';
            colorsInputContainer.style.display = 'none';
        }
        // Update the displayed value (remove %)
        bgThresholdValue.textContent = bgThresholdInput.value;
    }

    // --- Event Listeners for Parameter Changes (Trigger Reprocess) ---
    // Use correct IDs from index.html
    const colorCountSlider = document.getElementById('colors-input');
    const simplifyToleranceSlider = document.getElementById('detail-input'); // Detail slider
    // thresholdSlider reference is now bgThresholdInput
    // removeBackgroundCheckbox reference is removeBgCheckbox
    // modeRadios reference is modeRadios

    function triggerReprocess() {
        // Debounce: Clear existing timer and set a new one
        clearTimeout(reprocessTimer);
        reprocessTimer = setTimeout(() => {
            if (currentInputFilename) { // Only reprocess if a file was successfully uploaded initially
                reprocessImage();
            }
        }, 500); // Wait 500ms after the last change before reprocessing
    }

    if (colorCountSlider) colorCountSlider.addEventListener('input', () => {
        document.getElementById('colors-value').textContent = colorCountSlider.value; // Update color value display
        triggerReprocess();
    });
    if (simplifyToleranceSlider) simplifyToleranceSlider.addEventListener('input', () => {
        document.getElementById('detail-value').textContent = simplifyToleranceSlider.value; // Update detail value display
        triggerReprocess();
    });
    if (bgThresholdInput) bgThresholdInput.addEventListener('input', () => {
        bgThresholdValue.textContent = bgThresholdInput.value; // Update threshold value display (no %)
        triggerReprocess();
    });
    if (removeBgCheckbox) removeBgCheckbox.addEventListener('change', () => {
        updateThresholdControl(); // Update visibility/label first
        triggerReprocess();
    });
    modeRadios.forEach(radio => radio.addEventListener('change', () => {
        updateThresholdControl(); // Update visibility/label first
        triggerReprocess();
    }));

    // --- Initial Setup ---
    updateThresholdControl(); // Set initial state of threshold control
    // Set initial display values for sliders
    if (colorCountSlider) document.getElementById('colors-value').textContent = colorCountSlider.value;
    if (simplifyToleranceSlider) document.getElementById('detail-value').textContent = simplifyToleranceSlider.value;
    // Initial threshold value display is handled by updateThresholdControl

    // --- Reprocess Image Function ---
    async function reprocessImage() {
        if (!currentInputFilename) {
            // Should not happen if called correctly, but good practice
            console.warn("Reprocess called without an input filename.");
            return;
        }

        // Show spinner and hide previous errors
        uploadSpinner.style.display = 'block';
        errorMessage.style.display = 'none';
        // Don't clear the preview immediately, wait for the new result

        // Get current parameter values using correct IDs
        const colorCount = document.getElementById('colors-input').value;
        const simplifyTolerance = document.getElementById('detail-input').value; // Detail slider
        const threshold = bgThresholdInput.value; // Use variable
        const removeBackground = removeBgCheckbox.checked; // Use variable
        const mode = document.querySelector('input[name="mode"]:checked')?.value || 'color';

        const params = {
            input_filename: currentInputFilename,
            mode: mode,
            color_count: parseInt(colorCount, 10),
            simplify_tolerance: parseFloat(simplifyTolerance),
            // Send the threshold value (now 0-255) with the correct name from HTML
            bg_threshold: parseInt(threshold, 10),
            remove_background: removeBackground
        };

        try {
            const response = await fetch('/reprocess', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(params),
            });

            uploadSpinner.style.display = 'none'; // Hide spinner

            if (response.ok) {
                const resultData = await response.json();

                // Fetch the new SVG content
                const svgResponse = await fetch(resultData.svg_file_url);
                 if (!svgResponse.ok) {
                    throw new Error(`Failed to fetch reprocessed SVG: ${svgResponse.statusText}`);
                }
                const svgContent = await svgResponse.text();

                updateVectorizedPreview(svgContent); // Update preview and re-init panzoom

                 // Update download link
                const downloadLink = document.getElementById('download-link');
                if(downloadLink) {
                    downloadLink.href = resultData.download_url;
                    downloadLink.style.display = 'inline-block'; // Ensure link is visible
                }

            } else {
                const errorData = await response.json();
                showError(`Fehler beim Neuberechnen: ${errorData.error || response.statusText}`);
                 // Hide download link on error
                const downloadLink = document.getElementById('download-link');
                if(downloadLink) downloadLink.style.display = 'none';
            }
        } catch (error) {
            uploadSpinner.style.display = 'none'; // Hide spinner
            showError(`Fehler: ${error.message}`);
            console.error('Reprocess Error:', error);
             // Hide download link on error
            const downloadLink = document.getElementById('download-link');
            if(downloadLink) downloadLink.style.display = 'none';
        }
    }

});