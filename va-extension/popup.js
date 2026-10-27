document.getElementById('analyzeBtn').addEventListener('click', async () => {
    let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab.url && tab.url.includes("youtube.com/watch")) {
        const webAppUrl = `http://localhost:8000/process-extension?url=${encodeURIComponent(tab.url)}`;
        window.open(webAppUrl, '_blank');
    } else {
        alert("Please open a YouTube video page first.");
    }
});