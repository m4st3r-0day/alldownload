// Manda ad AllDownload: apre alldownload://add?url=... e il Mac passa il link all'app.
function send(url, tabId) {
  if (!url || !/^https?:/.test(url)) return;
  const target = "alldownload://add?url=" + encodeURIComponent(url);
  if (tabId !== undefined) chrome.tabs.update(tabId, { url: target });
  else chrome.tabs.create({ url: target });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "page", title: "Manda questa pagina ad AllDownload", contexts: ["page"] });
  chrome.contextMenus.create({ id: "link", title: "Manda il link ad AllDownload", contexts: ["link"] });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  send(info.menuItemId === "link" ? info.linkUrl : (info.pageUrl || (tab && tab.url)));
});

chrome.action.onClicked.addListener((tab) => send(tab.url));
