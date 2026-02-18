// ==================== //
// Global Variables     //
// ==================== //

let selectedFile = null;
let currentJobId = null;
let fileQueue = [];  // Multi-file queue

// Plan → max files per batch
const MAX_FILES_BY_PLAN = { free: 1, starter: 5, pro: 10, enterprise: 20 };

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

// File selected (supports multi-file for paid plans)
fileInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);
    const plan = getCachedUser()?.plan_tier?.toLowerCase() || 'free';
    const maxFiles = MAX_FILES_BY_PLAN[plan] || 1;

    if (files.length > 1 && maxFiles > 1) {
        // Multi-file mode
        const toAdd = files.slice(0, maxFiles - fileQueue.length);
        if (fileQueue.length + files.length > maxFiles) {
            showToast(`Max ${maxFiles} files per batch on your plan`, 'warning');
        }
        toAdd.forEach(f => addToQueue(f));
        renderQueue();
        document.getElementById('fileQueueSection').style.display = '';
        document.getElementById('splitBtn').style.display = 'block';
    } else {
        handleFileSelect(files[0]);
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
    const files = Array.from(e.dataTransfer.files);
    const plan = getCachedUser()?.plan_tier?.toLowerCase() || 'free';
    const maxFiles = MAX_FILES_BY_PLAN[plan] || 1;
    if (files.length > 1 && maxFiles > 1) {
        const toAdd = files.slice(0, maxFiles - fileQueue.length);
        toAdd.forEach(f => addToQueue(f));
        renderQueue();
        document.getElementById('fileQueueSection').style.display = '';
        splitBtn.style.display = 'block';
    } else if (files[0]) {
        handleFileSelect(files[0]);
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
    if (fileQueue.length > 0) {
        processQueue();
    } else if (selectedFile) {
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
    // Validate by extension (MIME type is unreliable)
    const allowed = ['.mp4', '.mov', '.avi', '.mkv'];
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!allowed.includes(ext)) {
        showError('Please select a valid video file (MP4, MOV, AVI, or MKV).');
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

function getCropParams() {
    const ar = document.getElementById('aspectRatioSelect')?.value || '';
    const pos = document.getElementById('cropPositionSelect')?.value || 'center';
    const cw = document.getElementById('customWidth')?.value || '';
    const ch = document.getElementById('customHeight')?.value || '';
    return { aspect_ratio: ar, crop_position: pos, custom_width: cw, custom_height: ch };
}

async function splitVideo() {
    if (!selectedFile) return;

    // Show processing section with progress
    showSection('processing');
    
    // Update processing message with percentage in spinner AND progress bar
    const processingSection = document.getElementById('processingSection');
    processingSection.innerHTML = `
    <div class="spinner-container">
        <div class="spinner"></div>
        <div class="spinner-percentage" id="uploadPercentage">0%</div>
    </div>
    <h3 id="uploadTitle">Uploading video...</h3>
    <div class="progress-bar-container">
        <div class="progress-bar">
            <div class="progress-bar-fill" id="progressBarFill" style="width: 0%"></div>
        </div>
    </div>
    <p id="uploadStatus">Preparing upload...</p>
`;

    const formData = new FormData();
    formData.append('file', selectedFile);
    const crop = getCropParams();
    if (crop.aspect_ratio) formData.append('aspect_ratio', crop.aspect_ratio);
    if (crop.crop_position) formData.append('crop_position', crop.crop_position);
    if (crop.custom_width)  formData.append('custom_width', crop.custom_width);
    if (crop.custom_height) formData.append('custom_height', crop.custom_height);

    const duration = segmentDuration.value;

    try {
        // Create XMLHttpRequest for progress tracking
        const xhr = new XMLHttpRequest();
        
        // Track upload progress
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = Math.round((e.loaded / e.total) * 100);
                const uploadPercentage = document.getElementById('uploadPercentage');
                const progressBarFill = document.getElementById('progressBarFill');
                const uploadStatus = document.getElementById('uploadStatus');
                
                // Update percentage in spinner
                if (uploadPercentage) {
                    uploadPercentage.textContent = percentComplete + '%';
                }
                
                // Update progress bar
                if (progressBarFill) {
                    progressBarFill.style.width = percentComplete + '%';
                }
                
                // Update status text
                if (uploadStatus) {
                    const uploadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
                    const totalMB = (e.total / (1024 * 1024)).toFixed(1);
                    uploadStatus.textContent = `Uploaded ${uploadedMB} MB of ${totalMB} MB`;
                }
            }
        });
        
        // When upload completes, show processing message
        xhr.upload.addEventListener('load', () => {
            const uploadTitle = document.getElementById('uploadTitle');
            const uploadStatus = document.getElementById('uploadStatus');
            const uploadPercentage = document.getElementById('uploadPercentage');
            const progressBarFill = document.getElementById('progressBarFill');
            
            if (uploadPercentage) {
                uploadPercentage.textContent = '100%';
            }
            if (progressBarFill) {
                progressBarFill.style.width = '100%';
            }
            if (uploadTitle) {
                uploadTitle.textContent = 'Processing video...';
            }
            if (uploadStatus) {
                uploadStatus.textContent = 'Splitting into segments...';
            }
        });
        
        // Handle completion
        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                const data = JSON.parse(xhr.responseText);
                currentJobId = data.job_id;
                displayResults(data);
            } else if (xhr.status === 401) {
                showError('Please sign in to upload videos.');
            } else if (xhr.status === 402) {
                showError('Monthly usage limit reached. Please upgrade your plan.');
            } else if (xhr.status === 429) {
                showError('Too many requests. Please wait a moment and try again.');
            } else {
                let detail = 'Failed to process video';
                try { detail = JSON.parse(xhr.responseText).detail; } catch(_) {}
                showError(detail);
            }
        });
        
        // Handle errors
        xhr.addEventListener('error', () => {
            showError('Network error. Check your connection and try again.');
        });
        
        // Send request (attach JWT if logged in)
        xhr.open('POST', `${API_BASE_URL}/api/v1/split?segment_duration=${duration}`);
        const token = typeof getToken === 'function' ? getToken() : localStorage.getItem('vs_access_token');
        if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);
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
// Crop Controls        //
// ==================== //

(function setupCropControls() {
    const arSelect   = document.getElementById('aspectRatioSelect');
    const posField   = document.getElementById('cropPositionField');
    const customDiv  = document.getElementById('cropCustom');
    if (!arSelect) return;

    arSelect.addEventListener('change', () => {
        const val = arSelect.value;
        posField.style.display = val ? '' : 'none';
        customDiv.style.display = val === 'custom' ? 'flex' : 'none';
    });
    posField.style.display = 'none'; // hidden until a ratio is chosen
})();

// ==================== //
// Multi-file Queue     //
// ==================== //

function addToQueue(file) {
    const allowed = ['.mp4', '.mov', '.avi', '.mkv'];
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!allowed.includes(ext)) { showToast(`${file.name} — unsupported format`, 'warning'); return; }
    if (file.size > 500 * 1024 * 1024) { showToast(`${file.name} exceeds 500MB`, 'warning'); return; }
    fileQueue.push({ id: Math.random().toString(36).slice(2), file, status: 'queued' });
}

function renderQueue() {
    const container = document.getElementById('fileQueue');
    const countEl   = document.getElementById('queueCount');
    if (!container) return;
    countEl.textContent = `${fileQueue.length} file${fileQueue.length !== 1 ? 's' : ''} queued`;
    container.innerHTML = fileQueue.map(item => `
        <div class="queue-item" data-id="${item.id}">
            <span class="queue-name">${item.file.name}</span>
            <span class="queue-size">${formatFileSize(item.file.size)}</span>
            <span class="queue-status status-${item.status}">${
                { queued: '⏳ Queued', uploading: '📤 Uploading', done: '✅ Done', failed: '❌ Failed' }[item.status] || item.status
            }</span>
            <button class="queue-remove-btn" onclick="removeFromQueue('${item.id}')">✕</button>
        </div>`).join('');
}

function removeFromQueue(id) {
    fileQueue = fileQueue.filter(f => f.id !== id);
    renderQueue();
    if (!fileQueue.length) {
        document.getElementById('fileQueueSection').style.display = 'none';
        splitBtn.style.display = 'none';
    }
}

async function processQueue() {
    if (!fileQueue.length) return;
    splitBtn.disabled = true;
    splitBtn.textContent = `Processing 0 / ${fileQueue.length}…`;

    let done = 0;
    for (const item of fileQueue) {
        item.status = 'uploading';
        renderQueue();
        try {
            const fd = new FormData();
            fd.append('file', item.file);
            const crop = getCropParams();
            if (crop.aspect_ratio) fd.append('aspect_ratio', crop.aspect_ratio);
            if (crop.crop_position) fd.append('crop_position', crop.crop_position);
            if (crop.custom_width)  fd.append('custom_width', crop.custom_width);
            if (crop.custom_height) fd.append('custom_height', crop.custom_height);
            const duration = segmentDuration.value;

            const res = await apiFetch(`/api/v1/split?segment_duration=${duration}`, { method: 'POST', body: fd });
            if (res.ok) {
                const data = await res.json();
                item.status = 'done';
                item.result = data;
                done++;
            } else {
                item.status = 'failed';
            }
        } catch (_) {
            item.status = 'failed';
        }
        splitBtn.textContent = `Processing ${done} / ${fileQueue.length}…`;
        renderQueue();
        await new Promise(r => setTimeout(r, 500)); // small delay between files
    }

    splitBtn.disabled = false;
    splitBtn.textContent = 'Split Video';
    const firstSuccess = fileQueue.find(f => f.status === 'done');
    if (firstSuccess) {
        currentJobId = firstSuccess.result.job_id;
        displayResults(firstSuccess.result);
    } else {
        showError('All files failed to process. Please try again.');
    }
}

// ==================== //
// Upload multi attr    //
// ==================== //

(function updateFileInputMultiple() {
    const user = getCachedUser();
    const plan = user?.plan_tier?.toLowerCase() || 'free';
    const maxFiles = MAX_FILES_BY_PLAN[plan] || 1;
    if (maxFiles > 1 && fileInput) {
        fileInput.setAttribute('multiple', 'multiple');
        const hint = document.getElementById('uploadAreaHint');
        if (hint) hint.textContent = `Supports: MP4, MOV, AVI, MKV · Up to ${maxFiles} files at once`;
    }
})();

// Clear queue button
document.getElementById('clearQueueBtn')?.addEventListener('click', () => {
    fileQueue = [];
    renderQueue();
    document.getElementById('fileQueueSection').style.display = 'none';
    splitBtn.style.display = 'none';
});

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

