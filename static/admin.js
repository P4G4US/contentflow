const contentFlowTypes = [
  { id: 'story', label: 'Story', accept: 'image/*,video/mp4,video/quicktime,video/webm,video/x-m4v', hint: 'Upload one image or video.' },
  { id: 'reel', label: 'Reel / video', accept: '.mp4,.mov,.webm,.m4v,video/*', hint: 'Upload one MP4, MOV, WEBM, or M4V video.' },
  { id: 'carousel', label: 'Carousel / static', accept: '.jpg,.jpeg,.png,.webp,.gif,image/*', hint: 'Upload up to 10 images in the order they should appear.' },
];
let contentStatusFilter = 'all';

const contentFlowStyles = document.createElement('style');
contentFlowStyles.textContent = `
.content-type-choices{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:8px 0 18px}
.content-type-choice{min-height:44px;padding:9px 10px;border:1px solid #dfe3ea;border-radius:7px;background:#fff;color:#354157;font-size:13px;font-weight:650}
.content-type-choice[aria-pressed="true"]{border-color:#5549d9;background:#f2f0ff;color:#3e35ad}
.bucket-stack{display:grid;gap:24px}
.client-review-group{scroll-margin-top:24px;border-top:1px solid #ebedf2;padding-top:20px}
.client-review-heading{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.client-review-heading h3{margin:0;font-size:16px}
.bucket-count{font-size:12px;color:#7b8497}
.bucket-empty{padding:16px 0;color:#7b8497;font-size:13px}
.bucket-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;padding:15px 12px;border-top:1px solid #f0f1f4;border-left:4px solid #d0d5dd;align-items:start}
.bucket-item.status-pending{border-left-color:#e9a426;background:#fffaf0}
.bucket-item.status-approved{border-left-color:#35966a;background:#f2fbf6}
.bucket-item.status-changes{border-left-color:#dc6b53;background:#fff7f5}
.bucket-item:first-child{border-top:0}
.bucket-item-title{font-weight:700;color:#263247}
.bucket-item-meta{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:5px;color:#7b8497;font-size:12px}
.bucket-item-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}
.review-filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 20px}
.review-filter-button{border:1px solid #dfe3ea;border-radius:6px;background:#fff;color:#475467;padding:7px 10px;font-size:12px;font-weight:650}
.review-filter-button[aria-pressed="true"]{border-color:#354157;background:#354157;color:white}
.review-filter-button[data-filter="pending"]{border-bottom:3px solid #e9a426}
.review-filter-button[data-filter="approved"]{border-bottom:3px solid #35966a}
.review-filter-button[data-filter="changes"]{border-bottom:3px solid #dc6b53}
.cards .card[data-review-filter]{cursor:pointer}
.cards .card[data-review-filter]:focus-visible{outline:3px solid #5549d9;outline-offset:2px}
.cards .card[data-review-filter="pending"]{border-top:4px solid #e9a426}
.cards .card[data-review-filter="approved"]{border-top:4px solid #35966a}
.cards .card[data-review-filter="changes"]{border-top:4px solid #dc6b53}
.client-message-banner{margin:0 0 24px;padding:16px 18px;background:#eff6ff;border-left:4px solid #3677bd;border-radius:4px;color:#244a70}
.client-message-banner strong{display:block;margin-bottom:4px;font-size:13px}
.client-message-banner p{margin:0;white-space:pre-wrap}
.client-admin-actions{padding:10px}
.client-admin-action-group{display:flex;flex-wrap:wrap;gap:8px}
.media-link-actions{display:flex;gap:10px}
.media-view,.media-download{width:max-content;color:#4758d3;font-size:12px;font-weight:650}
.media-view{text-decoration:underline}
.media-previews{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,150px));gap:8px;margin-top:12px}
.media-previews img,.media-previews video{display:block;width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:6px;background:#f2f4f7}
.media-preview-item{display:grid;align-content:start;gap:5px;min-width:0}
.voice-feedback{display:grid;gap:8px;margin:14px 0;padding:12px;background:#f7f8fa;border:1px solid #ebedf2;border-radius:7px}
.voice-feedback strong{font-size:13px}
.voice-feedback audio{width:min(100%,360px);height:38px}
.voice-recorder{display:grid;gap:10px;padding:14px 0;border-top:1px solid #ebedf2}
.voice-recorder-controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.voice-recorder-status{color:#7b8497;font-size:12px}
.voice-preview{width:100%;height:40px}
.submission-hint{margin:6px 0 0;color:#7b8497;font-size:12px}
.selected-media{margin:8px 0 0;color:#475467;font-size:12px}
@media(max-width:600px){.content-type-choices{grid-template-columns:1fr}.bucket-item{grid-template-columns:1fr}.bucket-item-actions{justify-content:flex-start}}
`;
document.head.append(contentFlowStyles);

function contentFlowTypeLabel(type) {
  return contentFlowTypes.find((item) => item.id === type)?.label || 'Reel / video';
}

function contentFlowMedia(post, isClient = false) {
  const mediaItems = post.media?.length
    ? post.media
    : post.filename
      ? [{ id: null, filename: post.filename, original_filename: post.original_filename || post.filename, media_type: 'video/mp4' }]
      : [];
  if (!mediaItems.length) return '<p class="bucket-empty">No media attached.</p>';
  const token = isClient ? `?token=${encodeURIComponent(clientToken)}` : '';
  return `<div class="media-previews">${mediaItems.map((media) => {
    const source = media.id
      ? `/api/media/${media.id}${token}`
      : `/api/video/${post.id}${token}`;
    const separator = source.includes('?') ? '&' : '?';
    const name = e(media.original_filename || 'Uploaded media');
    const preview = media.media_type?.startsWith('image/')
      ? `<img src="${source}" alt="${name}" loading="lazy">`
      : `<video src="${source}" controls preload="metadata" aria-label="${name}"></video>`;
    return `<div class="media-preview-item">${preview}<div class="media-link-actions"><a class="media-view" href="${source}" target="_blank" rel="noopener">View</a><a class="media-download" href="${source}${separator}download=true" download="${name}">Download</a></div></div>`;
  }).join('')}</div>`;
}

function contentFlowVoiceFeedback(post, isClient = false) {
  const notes = post.feedback_media || [];
  if (!notes.length) return '';
  const token = isClient ? `?token=${encodeURIComponent(clientToken)}` : '';
  return `<section class="voice-feedback"><strong>${isClient ? 'Your voice feedback' : 'Client voice feedback'}</strong>${notes.map((note) => `<audio controls preload="none" src="/api/feedback-media/${note.id}${token}" aria-label="Client voice feedback"></audio>`).join('')}</section>`;
}

function renderContentBuckets(panel) {
  panel.dataset.contentFlowBuckets = 'true';
  const filterItems = [
    ['all', 'All content'], ['pending', 'Awaiting review'], ['approved', 'Approved'], ['changes', 'Needs changes'],
  ];
  const filteredPosts = posts.filter((post) => contentStatusFilter === 'all' || post.status === contentStatusFilter);
  const groups = new Map();
  for (const post of filteredPosts) {
    const key = String(post.client_id ?? post.client_name);
    if (!groups.has(key)) groups.set(key, { name: post.client_name, posts: [] });
    groups.get(key).posts.push(post);
  }
  const content = [...groups.values()].map((group) => `<section class="client-review-group"><div class="client-review-heading"><h3>${e(group.name)}</h3><span class="bucket-count">${group.posts.length} ${group.posts.length === 1 ? 'item' : 'items'}</span></div>${group.posts.map((post) => {
    const typeLabel = contentFlowTypeLabel(post.content_type);
    return `<article class="bucket-item status-${e(post.status)}"><div><div class="bucket-item-title">${e(post.title)}</div><div class="bucket-item-meta"><span class="pill ${e(post.status)}">${e(status(post.status))}</span><span>${e(typeLabel)}</span><span>${e(fmt(post.publish_at))}</span></div>${post.feedback ? `<p class="muted"><b>Client feedback:</b> ${e(post.feedback)}</p>` : ''}${contentFlowMedia(post)}${contentFlowVoiceFeedback(post)}</div><div class="bucket-item-actions"><button class="btn ghost" data-copy-review="${e(post.client_token)}" data-post="${post.id}">Copy review link</button>${post.status !== 'pending' ? `<button class="btn ghost" data-resubmit="${post.id}">Resubmit</button>` : ''}<button class="btn bad" data-delete-post="${post.id}">Delete</button></div></article>`;
  }).join('')}</section>`).join('');
  panel.id = 'content-review-panel';
  panel.innerHTML = `<div class="panelhead"><div><h2>Content review</h2><span class="micro">Submissions grouped by client.</span></div></div><div class="review-filters">${filterItems.map(([filter, label]) => `<button type="button" class="review-filter-button" data-status-filter="${filter}" aria-pressed="${contentStatusFilter === filter}">${label}</button>`).join('')}</div><div class="bucket-stack">${content || '<div class="bucket-empty">No content matches this status.</div>'}</div>`;
}

function openContentSubmission() {
  if (!clients.length) {
    toast('Create a client first');
    return;
  }
  const clientOptions = clients.map((client) => `<option value="${client.id}">${e(client.name)}</option>`).join('');
  const dialog = modal(`<div class="head"><h2>New content</h2><button class="close" aria-label="Close">×</button></div><form id="contentSubmissionForm"><div class="field"><label for="submissionClient">Client</label><select id="submissionClient" name="client_id" required>${clientOptions}</select></div><fieldset style="border:0;padding:0;margin:0"><legend class="field-label">Content type</legend><div class="content-type-choices">${contentFlowTypes.map((type) => `<button type="button" class="content-type-choice" data-content-type="${type.id}" aria-pressed="${type.id === 'reel'}">${type.label}</button>`).join('')}</div></fieldset><input type="hidden" name="content_type" value="reel"><div class="field"><label for="submissionTitle">Title</label><input id="submissionTitle" name="title" required maxlength="200" placeholder="Summer launch story"></div><div class="field"><label for="submissionMedia">Media</label><input id="submissionMedia" name="media_files" type="file" accept="${contentFlowTypes[1].accept}" required><p class="submission-hint" id="submissionHint">${contentFlowTypes[1].hint}</p><p class="selected-media" id="selectedMedia"></p></div><div class="field"><label for="submissionCaption">Proposed caption</label><textarea id="submissionCaption" name="caption" maxlength="10000" placeholder="Write your suggested caption..."></textarea></div><div class="field"><label for="submissionPublishAt">Proposed publish date (optional)</label><input id="submissionPublishAt" name="publish_at" type="datetime-local"></div><button class="btn" id="submissionButton">Send for approval</button></form>`);
  const form = dialog.querySelector('#contentSubmissionForm');
  const typeField = form.elements.namedItem('content_type');
  const mediaInput = dialog.querySelector('#submissionMedia');
  const hint = dialog.querySelector('#submissionHint');
  const selectedMedia = dialog.querySelector('#selectedMedia');
  const typeButtons = [...dialog.querySelectorAll('[data-content-type]')];

  typeButtons.forEach((button) => button.addEventListener('click', () => {
    const selectedType = contentFlowTypes.find((type) => type.id === button.dataset.contentType);
    typeField.value = selectedType.id;
    mediaInput.value = '';
    mediaInput.accept = selectedType.accept;
    mediaInput.multiple = selectedType.id === 'carousel';
    hint.textContent = selectedType.hint;
    selectedMedia.textContent = '';
    typeButtons.forEach((choice) => choice.setAttribute('aria-pressed', String(choice === button)));
  }));

  mediaInput.addEventListener('change', () => {
    selectedMedia.textContent = [...mediaInput.files].map((file) => file.name).join(', ');
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = dialog.querySelector('#submissionButton');
    submitButton.disabled = true;
    submitButton.textContent = 'Uploading...';
    try {
      const result = await api('/api/posts', { method: 'POST', body: new FormData(form) });
      dialog.remove();
      toast(result.notification === 'sent' ? 'Submitted and client emailed' : 'Submitted in the matching content section');
      go();
    } catch (error) {
      toast(error.message);
      submitButton.disabled = false;
      submitButton.textContent = 'Send for approval';
    }
  });
}

function setClientBanner(portal, message) {
  let banner = portal.querySelector('.client-message-banner');
  if (!message) {
    banner?.remove();
    return;
  }
  if (!banner) {
    banner = document.createElement('aside');
    banner.className = 'client-message-banner';
    banner.setAttribute('role', 'status');
    banner.innerHTML = '<strong>Message from your content manager</strong><p></p>';
    portal.querySelector('.portaltop')?.insertAdjacentElement('afterend', banner);
  }
  banner.querySelector('p').textContent = message;
}

function startClientBannerRefresh(portal) {
  if (portal.dataset.messageRefreshStarted === 'true') return;
  portal.dataset.messageRefreshStarted = 'true';
  const timer = setInterval(async () => {
    if (!portal.isConnected) {
      clearInterval(timer);
      return;
    }
    try {
      const result = await api(`/api/portal/${encodeURIComponent(clientToken)}/message`);
      setClientBanner(portal, result.message);
    } catch {
      clearInterval(timer);
    }
  }, 15000);
}

function openClientMessage(clientId) {
  const client = clients.find((item) => item.id === Number(clientId));
  if (!client) return;
  const dialog = modal(`<div class="head"><h2>Message ${e(client.name)}</h2><button class="close" aria-label="Close">×</button></div><form id="clientMessageForm"><div class="field"><label for="clientBannerMessage">Banner message</label><textarea id="clientBannerMessage" name="message" maxlength="2000" placeholder="Write a message that will appear in this client’s portal...">${e(client.admin_message || '')}</textarea><span class="micro">The banner appears in their private portal. You can clear it at any time.</span></div><div class="client-admin-actions"><button class="btn" type="submit">Save banner</button>${client.admin_message ? '<button class="btn ghost" type="button" id="clearClientBanner">Clear banner</button>' : ''}</div></form>`);
  const saveMessage = async (message) => {
    try {
      await api(`/api/clients/${client.id}/message`, json('PUT', { message }));
      dialog.remove();
      toast(message.trim() ? 'Client banner updated' : 'Client banner cleared');
      go();
    } catch (error) {
      toast(error.message);
    }
  };
  dialog.querySelector('#clientMessageForm').addEventListener('submit', (event) => {
    event.preventDefault();
    saveMessage(dialog.querySelector('#clientBannerMessage').value);
  });
  dialog.querySelector('#clearClientBanner')?.addEventListener('click', () => saveMessage(''));
}

function addClientActions() {
  const table = [...contentFlowRoot.querySelectorAll('.main table')]
    .find((candidate) => candidate.tHead?.textContent.includes('Client'));
  if (!table) return;
  const header = table.tHead?.rows[0];
  if (header && !header.querySelector('[data-client-actions-heading]')) {
    const heading = document.createElement('th');
    heading.dataset.clientActionsHeading = 'true';
    heading.textContent = 'Actions';
    header.append(heading);
  }
  clients.forEach((client, index) => {
    const row = table.tBodies[0]?.rows[index];
    if (!row || row.dataset.clientActionsReady === 'true' || row.querySelector('[colspan]')) return;
    const actions = document.createElement('td');
    actions.className = 'client-admin-actions';
    actions.innerHTML = `<div class="client-admin-action-group"><button type="button" class="btn ghost" data-message-client="${client.id}">${client.admin_message ? 'Edit message' : 'Message'}</button><button type="button" class="btn bad" data-delete-client="${client.id}">Delete client</button></div>`;
    row.append(actions);
    row.dataset.clientActionsReady = 'true';
  });
}

function prepareOverviewCards() {
  const filters = ['all', 'pending', 'approved', 'changes'];
  contentFlowRoot.querySelectorAll('.cards .card').forEach((card, index) => {
    const filter = filters[index];
    if (!filter) return;
    card.dataset.reviewFilter = filter;
    card.setAttribute('role', 'button');
    card.tabIndex = 0;
    card.setAttribute('aria-label', `View ${card.querySelector('small')?.textContent || 'content'} in Content review`);
  });
}

function showContentFilter(filter) {
  contentStatusFilter = filter;
  const panel = contentFlowRoot.querySelector('#content-review-panel');
  if (panel) renderContentBuckets(panel);
  contentFlowRoot.querySelectorAll('.sidebar .nav').forEach((item) => {
    item.classList.toggle('active', item.textContent.includes('Content review'));
  });
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function openChangeRequest(postId) {
  const dialog = modal(`<div class="head"><h2>Request a change</h2><button class="close" aria-label="Close">×</button></div><form id="changeRequestForm"><div class="field"><label for="changeDescription">Describe what you’d like changed</label><textarea id="changeDescription" name="feedback" maxlength="2000" placeholder="Type your feedback, or record a voice note below."></textarea></div><div class="voice-recorder"><strong>Voice note (optional)</strong><div class="voice-recorder-controls"><button type="button" class="btn ghost" id="recordVoice">Record voice note</button><button type="button" class="btn ghost" id="clearVoice" hidden>Remove recording</button><span class="voice-recorder-status" id="recordingStatus">You can listen before sending.</span></div><audio class="voice-preview" id="voicePreview" controls hidden></audio></div><button class="btn bad" id="sendChangeRequest">Send change request</button></form>`);
  const form = dialog.querySelector('#changeRequestForm');
  const recordButton = dialog.querySelector('#recordVoice');
  const clearButton = dialog.querySelector('#clearVoice');
  const recordingStatus = dialog.querySelector('#recordingStatus');
  const voicePreview = dialog.querySelector('#voicePreview');
  let recorder = null;
  let audioStream = null;
  let recordedChunks = [];
  let voiceBlob = null;
  let previewUrl = null;

  const stopTracks = () => {
    audioStream?.getTracks().forEach((track) => track.stop());
    audioStream = null;
  };
  const clearPreview = () => {
    voiceBlob = null;
    recordedChunks = [];
    voicePreview.pause();
    voicePreview.removeAttribute('src');
    voicePreview.hidden = true;
    clearButton.hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  };
  const closeRecorder = () => {
    if (recorder?.state === 'recording') recorder.stop();
    stopTracks();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  };

  recordButton.addEventListener('click', async () => {
    if (recorder?.state === 'recording') {
      recordButton.disabled = true;
      recorder.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      recordingStatus.textContent = 'Voice recording is not supported in this browser.';
      return;
    }
    try {
      clearPreview();
      audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const supportedTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = supportedTypes.find((type) => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(audioStream, mimeType ? { mimeType } : undefined);
      recordedChunks = [];
      recorder.addEventListener('dataavailable', (event) => {
        if (event.data.size) recordedChunks.push(event.data);
      });
      recorder.addEventListener('stop', () => {
        voiceBlob = new Blob(recordedChunks, { type: recorder.mimeType || 'audio/webm' });
        previewUrl = URL.createObjectURL(voiceBlob);
        voicePreview.src = previewUrl;
        voicePreview.hidden = false;
        clearButton.hidden = false;
        recordButton.disabled = false;
        recordButton.textContent = 'Record again';
        recordingStatus.textContent = 'Play your recording before sending.';
        stopTracks();
      }, { once: true });
      recorder.start();
      recordButton.textContent = 'Stop recording';
      recordingStatus.textContent = 'Recording. Select stop when you’re done.';
    } catch {
      stopTracks();
      recordingStatus.textContent = 'Microphone access was unavailable. You can still type feedback.';
    }
  });

  clearButton.addEventListener('click', () => {
    clearPreview();
    recordButton.textContent = 'Record voice note';
    recordingStatus.textContent = 'You can listen before sending.';
  });
  dialog.querySelector('.close').addEventListener('click', closeRecorder);
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) closeRecorder();
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (recorder?.state === 'recording') {
      toast('Stop the recording before sending');
      return;
    }
    const description = form.elements.namedItem('feedback').value.trim();
    if (!description && !voiceBlob) {
      toast('Write a description or record a voice note');
      return;
    }
    const payload = new FormData();
    payload.append('action', 'changes');
    payload.append('feedback', description);
    if (voiceBlob) {
      const extension = voiceBlob.type.includes('mp4') ? 'm4a' : voiceBlob.type.includes('ogg') ? 'ogg' : 'webm';
      payload.append('voice_note', voiceBlob, `voice-feedback.${extension}`);
    }
    const submitButton = dialog.querySelector('#sendChangeRequest');
    submitButton.disabled = true;
    submitButton.textContent = 'Sending...';
    try {
      await api(`/api/portal/${encodeURIComponent(clientToken)}/posts/${postId}/decision`, { method: 'POST', body: payload });
      closeRecorder();
      dialog.remove();
      toast('Change request sent');
      go();
    } catch (error) {
      toast(error.message);
      submitButton.disabled = false;
      submitButton.textContent = 'Send change request';
    }
  });
}

async function enhanceClientContent(portal) {
  if (portal.dataset.contentFlowMedia === 'loading' || portal.dataset.contentFlowMedia === 'ready') return;
  portal.dataset.contentFlowMedia = 'loading';
  try {
    const result = await api(`/api/portal/${encodeURIComponent(clientToken)}`);
    setClientBanner(portal, result.client.admin_message);
    startClientBannerRefresh(portal);
    for (const post of result.posts) {
      const card = portal.querySelector(`#post-${post.id}`);
      if (!card) continue;
      card.dataset.contentType = post.content_type || 'reel';
      const mediaContainer = card.firstElementChild;
      if (mediaContainer) mediaContainer.innerHTML = contentFlowMedia(post, true);
      const details = card.children[1];
      const title = details?.querySelector('h2');
      if (title && !details.querySelector('[data-content-type-label]')) {
        const label = document.createElement('span');
        label.className = 'pill';
        label.dataset.contentTypeLabel = 'true';
        label.textContent = contentFlowTypeLabel(post.content_type);
        details.insertBefore(label, title);
      }
      portal.querySelectorAll('[data-approve]').forEach((button) => { button.textContent = 'Approved'; });
      portal.querySelectorAll('[data-changes]').forEach((button) => { button.textContent = 'Need change'; });
      const feedbackParagraph = details?.querySelector('.muted b')?.parentElement;
      if (feedbackParagraph && !post.feedback) feedbackParagraph.innerHTML = '<b>Change request sent.</b>';
      if (post.feedback_media?.length && !details.querySelector('.voice-feedback')) {
        details.querySelector('.caption')?.insertAdjacentHTML('afterend', contentFlowVoiceFeedback(post, true));
      }
    }
    portal.dataset.contentFlowMedia = 'ready';
  } catch {
    portal.dataset.contentFlowMedia = 'error';
  }
}

const contentFlowRoot = document.querySelector('#app');
contentFlowRoot.addEventListener('click', (event) => {
  const filterButton = event.target.closest('[data-status-filter]');
  if (filterButton) {
    showContentFilter(filterButton.dataset.statusFilter);
    return;
  }
  const summaryCard = event.target.closest('[data-review-filter]');
  if (summaryCard) showContentFilter(summaryCard.dataset.reviewFilter);
});
contentFlowRoot.addEventListener('keydown', (event) => {
  const summaryCard = event.target.closest('[data-review-filter]');
  if (summaryCard && (event.key === 'Enter' || event.key === ' ')) {
    event.preventDefault();
    showContentFilter(summaryCard.dataset.reviewFilter);
  }
});
contentFlowRoot.addEventListener('click', (event) => {
  const changeButton = event.target.closest('[data-changes]');
  if (changeButton) {
    event.preventDefault();
    event.stopImmediatePropagation();
    openChangeRequest(changeButton.dataset.changes);
  }
}, true);
contentFlowRoot.addEventListener('click', async (event) => {
  const messageButton = event.target.closest('[data-message-client]');
  if (messageButton) {
    openClientMessage(messageButton.dataset.messageClient);
    return;
  }
  const deleteClientButton = event.target.closest('[data-delete-client]');
  if (deleteClientButton) {
    const client = clients.find((item) => item.id === Number(deleteClientButton.dataset.deleteClient));
    if (!client || !confirm(`Delete ${client.name} and all of their content? This cannot be undone.`)) return;
    try {
      const result = await api(`/api/clients/${client.id}`, { method: 'DELETE' });
      toast(`Client deleted with ${result.posts_deleted} content items`);
      go();
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  const deletePostButton = event.target.closest('[data-delete-post]');
  if (deletePostButton) {
    const post = posts.find((item) => item.id === Number(deletePostButton.dataset.deletePost));
    if (!post || !confirm(`Delete “${post.title}” and its uploaded media? This cannot be undone.`)) return;
    try {
      await api(`/api/posts/${post.id}`, { method: 'DELETE' });
      toast('Content deleted');
      go();
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  const copyButton = event.target.closest('[data-copy-review]');
  if (copyButton) {
    const link = `${location.origin}/?client=${encodeURIComponent(copyButton.dataset.copyReview)}&post=${copyButton.dataset.post}`;
    try {
      await navigator.clipboard.writeText(link);
      toast('Review link copied');
    } catch {
      prompt('Copy this review link', link);
    }
    return;
  }
  const resubmitButton = event.target.closest('[data-resubmit]');
  if (resubmitButton && confirm('Send this item back for client review?')) {
    try {
      await api(`/api/posts/${resubmitButton.dataset.resubmit}/resubmit`, { method: 'POST' });
      toast('Sent for review');
      go();
    } catch (error) {
      toast(error.message);
    }
  }
});

function enhanceContentFlow() {
  const newContentButton = contentFlowRoot.querySelector('#newPost');
  if (newContentButton && newContentButton.dataset.contentFlowReady !== 'true') {
    newContentButton.dataset.contentFlowReady = 'true';
    newContentButton.onclick = openContentSubmission;
  }
  const contentPanel = contentFlowRoot.querySelector('.main > .panel');
  if (contentPanel && contentPanel.dataset.contentFlowBuckets !== 'true') {
    renderContentBuckets(contentPanel);
  }
  if (contentFlowRoot.querySelector('.cards')) prepareOverviewCards();
  if (contentFlowRoot.querySelector('.main table')) addClientActions();
  const portal = contentFlowRoot.querySelector('.portal');
  if (portal) enhanceClientContent(portal);
}

new MutationObserver(enhanceContentFlow).observe(contentFlowRoot, { childList: true, subtree: true });
enhanceContentFlow();