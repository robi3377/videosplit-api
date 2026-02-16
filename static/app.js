// ==================== //
// Global Variables     //
// ==================== //

let selectedFile = null;
let currentJobId = null;

// API Base URL - change this when deploying
const API_BASE_URL = window.location.origin;

// ==================== //
// DOM Elements         //
// ==================== //

// Sections
const uploadSection = document.getElementById('uploadSection');
const processingSection = document.getElementById('processingSection');
const resultsSection = document.getElementById('resultsSection');
const errorSection = document.getElementById('errorSection');

// Upload elements
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const fileSize = document.getElementById('fileSize');
const removeFile = document.getElementById('removeFile');

// Duration control
const durationControl = document.getElementById('durationControl');
const segmentDuration = document.getElementById('segmentDuration');
const durationValue = document.getElementById('durationValue');

// Buttons
const splitBtn = document.getElementById('splitBtn');
const splitAnotherBtn = document.getElementById('splitAnotherBtn');
const tryAgainBtn = document.getElementById('tryAgainBtn');
const downloadAllBtn = document.getElementById('downloadAllBtn');

// Results elements
const originalFileName = document.getElementById('originalFileName');
const totalDuration = document.getElementById('totalDuration');
const segmentCount = document.getElementById('segmentCount');
const segmentsList = document.getElementById('segmentsList');

// Error elements
const errorMessage = document.getElementById('errorMessage');

// Modal elements
const tutorialModal = document.getElementById('tutorialModal');
const closeModal = document.getElementById('closeModal');
const gotItBtn = document.getElementById('gotItBtn');
const dontShowAgain = document.getElementById('dontShowAgain');
const helpBtn = document.getElementById('helpBtn');
const footerHelpBtn = document.getElementById('footerHelpBtn');

// ==================== //
// Event Listeners      //
// ==================== //

// Click to upload
uploadArea.addEventListener('click', () => {
    fileInput.click();
});

// File selected
fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        handleFileSelect(file);
    }
});

// Drag and drop
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    
    const file = e.dataTransfer.files[0];
    if (file) {
        handleFileSelect(file);
    }
});

// Remove file
removeFile.addEventListener('click', () => {
    resetUpload();
});

// Duration slider
segmentDuration.addEventListener('input', (e) => {
    const value = e.target.value;
    updateDurationDisplay(value);
});

// Split button
splitBtn.addEventListener('click', () => {
    if (selectedFile) {
        splitVideo();
    }
});

// Split another video
splitAnotherBtn.addEventListener('click', () => {
    resetUpload();
});

// Try again button
tryAgainBtn.addEventListener('click', () => {
    showSection('upload');
});

// Download all button
downloadAllBtn.addEventListener('click', () => {
    downloadAllSegments();
});

// Modal controls
closeModal.addEventListener('click', () => {
    closeTutorialModal();
});

gotItBtn.addEventListener('click', () => {
    if (dontShowAgain.checked) {
        localStorage.setItem('hideTutorial', 'true');
    }
    closeTutorialModal();
});

helpBtn.addEventListener('click', () => {
    showTutorialModal();
});

footerHelpBtn.addEventListener('click', (e) => {
    e.preventDefault();
    showTutorialModal();
});

// Close modal on outside click
window.addEventListener('click', (e) => {
    if (e.target === tutorialModal) {
        closeTutorialModal();
    }
});

// ==================== //
// Modal Functions      //
// ==================== //

function showTutorialModal() {
    tutorialModal.classList.add('show');
}

function closeTutorialModal() {
    tutorialModal.classList.remove('show');
}

// ==================== //
// File Handling        //
// ==================== //

function handleFileSelect(file) {
    // Validate file type
    if (!file.type.startsWith('video/')) {
        showError('Please select a valid video file.');
        return;
    }

    // Validate file size (500MB max)
    const maxSize = 500 * 1024 * 1024; // 500MB in bytes
    if (file.size > maxSize) {
        showError('File size exceeds 500MB limit. Please select a smaller file.');
        return;
    }

    // Store file
    selectedFile = file;

    // Update UI
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);

    // Show file info and split button
    fileInfo.style.display = 'block';
    splitBtn.style.display = 'block';
}

function resetUpload() {
    selectedFile = null;
    currentJobId = null;
    fileInput.value = '';

    // Reset UI
    fileInfo.style.display = 'none';
    splitBtn.style.display = 'none';

    // Show upload section
    showSection('upload');
}

// ==================== //
// Video Processing     //
// ==================== //

async function splitVideo() {
    if (!selectedFile) return;

    // Show processing section with progress
    showSection('processing');
    
    // Update processing message
    const processingSection = document.getElementById('processingSection');
    processingSection.innerHTML = `
        <div class="spinner"></div>
        <h3>Uploading video...</h3>
        <div style="width: 300px; margin: 20px auto; background: #ddd; border-radius: 10px; height: 30px; overflow: hidden;">
            <div id="progressBar" style="width: 0%; height: 100%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); transition: width 0.3s; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 14px;">0%</div>
        </div>
        <p id="uploadStatus">Preparing upload...</p>
    `;

    const formData = new FormData();
    formData.append('file', selectedFile);

    const duration = segmentDuration.value;

    try {
        // Create XMLHttpRequest for progress tracking
        const xhr = new XMLHttpRequest();
        
        // Track upload progress
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                const progressBar = document.getElementById('progressBar');
                const uploadStatus = document.getElementById('uploadStatus');
                
                if (progressBar) {
                    progressBar.style.width = percentComplete + '%';
                    progressBar.textContent = Math.round(percentComplete) + '%';
                }
                
                if (uploadStatus) {
                    const uploadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
                    const totalMB = (e.total / (1024 * 1024)).toFixed(1);
                    uploadStatus.textContent = `Uploaded ${uploadedMB} MB of ${totalMB} MB`;
                }
            }
        });
        
        // When upload completes, show processing message
        xhr.upload.addEventListener('load', () => {
            const uploadStatus = document.getElementById('uploadStatus');
            if (uploadStatus) {
                uploadStatus.textContent = 'Upload complete! Processing video...';
            }
        });
        
        // Handle completion
        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                const data = JSON.parse(xhr.responseText);
                currentJobId = data.job_id;
                displayResults(data);
            } else {
                const errorData = JSON.parse(xhr.responseText);
                throw new Error(errorData.detail || 'Failed to process video');
            }
        });
        
        // Handle errors
        xhr.addEventListener('error', () => {
            throw new Error('Network error occurred');
        });
        
        // Send request
        xhr.open('POST', `${API_BASE_URL}/api/v1/split?segment_duration=${duration}`);
        xhr.send(formData);

    } catch (error) {
        console.error('Error:', error);
        showError(error.message || 'An unexpected error occurred. Please try again.');
    }
}

function displayResults(data) {
    // Update info
    originalFileName.textContent = data.original_filename;
    totalDuration.textContent = formatDuration(data.total_duration);
    segmentCount.textContent = data.segments_count;

    // Clear previous segments
    segmentsList.innerHTML = '';

    // Add segments
    data.segments.forEach((segment, index) => {
        const segmentItem = createSegmentItem(segment, index + 1);
        segmentsList.appendChild(segmentItem);
    });

    // Show results section
    showSection('results');
}

function createSegmentItem(segment, index) {
    const item = document.createElement('div');
    item.className = 'segment-item';

    const info = document.createElement('div');
    info.className = 'segment-info';

    const name = document.createElement('span');
    name.className = 'segment-name';
    name.textContent = `Segment ${index}`;

    const details = document.createElement('span');
    details.className = 'segment-details';
    details.textContent = `${formatDuration(segment.duration)} • ${formatFileSize(segment.size_bytes)}`;

    info.appendChild(name);
    info.appendChild(details);

    const downloadBtn = document.createElement('button');
    downloadBtn.className = 'download-btn';
    downloadBtn.textContent = '⬇ Download';
    downloadBtn.onclick = () => downloadSegment(segment.download_url, segment.filename);

    item.appendChild(info);
    item.appendChild(downloadBtn);

    return item;
}

// ==================== //
// Download Functions   //
// ==================== //

function downloadSegment(url, filename) {
    const link = document.createElement('a');
    link.href = API_BASE_URL + url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function downloadAllSegments() {
    if (!currentJobId) {
        showError('Job ID not found. Cannot download segments.');
        return;
    }

    // Show loading state
    downloadAllBtn.textContent = '⏳ Preparing ZIP...';
    downloadAllBtn.disabled = true;

    // Download as ZIP
    const zipUrl = `${API_BASE_URL}/api/v1/download-all/${currentJobId}`;
    
    const link = document.createElement('a');
    link.href = zipUrl;
    link.download = `segments_${currentJobId}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Reset button after delay
    setTimeout(() => {
        downloadAllBtn.textContent = '📦 Download All as ZIP';
        downloadAllBtn.disabled = false;
    }, 3000);
}

// ==================== //
// UI Helper Functions  //
// ==================== //

function showSection(section) {
    // Hide all sections
    uploadSection.style.display = 'none';
    processingSection.style.display = 'none';
    resultsSection.style.display = 'none';
    errorSection.style.display = 'none';

    // Show requested section
    switch(section) {
        case 'upload':
            uploadSection.style.display = 'block';
            break;
        case 'processing':
            processingSection.style.display = 'block';
            break;
        case 'results':
            resultsSection.style.display = 'block';
            break;
        case 'error':
            errorSection.style.display = 'block';
            break;
    }
}

function showError(message) {
    errorMessage.textContent = message;
    showSection('error');
}

function updateDurationDisplay(seconds) {
    let display;
    
    if (seconds < 60) {
        display = `${seconds} seconds`;
    } else if (seconds === 60) {
        display = '1 minute';
    } else if (seconds < 120) {
        display = `${seconds} seconds`;
    } else {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        if (secs === 0) {
            display = `${minutes} minutes`;
        } else {
            display = `${minutes}m ${secs}s`;
        }
    }
    
    durationValue.textContent = display;
}

// ==================== //
// Utility Functions    //
// ==================== //

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);

    if (mins === 0) {
        return `${secs}s`;
    } else if (secs === 0) {
        return `${mins}m`;
    } else {
        return `${mins}m ${secs}s`;
    }
}

// ==================== //
// Initialize           //
// ==================== //

// Set initial duration display
updateDurationDisplay(segmentDuration.value);

// Show upload section on load
showSection('upload');

// Show tutorial modal on first visit
if (!localStorage.getItem('hideTutorial')) {
    setTimeout(() => {
        showTutorialModal();
    }, 500);
}

console.log('VideoSplit initialized!');
console.log('API Base URL:', API_BASE_URL);