// Guest requests use one revision-checked transaction. Stage bytes in a private temporary
// file so a malformed or stale request cannot overwrite the last playable path in RAM.
File guestFile;
size_t guestBytes = 0;
int guestUploadError = 0;
bool guestLocked = false;
const char* GUEST_TMP = "/guest.tmp";
void guestClose() {
  if (!guestLocked) return;
  if (guestFile) guestFile.close();
  LittleFS.remove(GUEST_TMP);
  guestLocked = false;
  flashEnd();
}
void guestRaw() {
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    guestClose();
    guestBytes = 0;
    guestUploadError = 0;
    if (!fsOk || !pat) { guestUploadError = 503; return; }
    if (busy() || stepN || bootPending || autoOn || !homed || fault || !flashBegin()) {
      guestUploadError = 409; return;
    }
    guestLocked = true;
    guestFile = LittleFS.open(GUEST_TMP, "w+");
    if (!guestFile) guestUploadError = 507;
  } else if (r.status == RAW_WRITE && !guestUploadError) {
    if (r.currentSize > sizeof(Pt) * MAXPTS * 3 - guestBytes) guestUploadError = 413;
    else if (guestFile.write(r.buf, r.currentSize) != r.currentSize) guestUploadError = 507;
    else guestBytes += r.currentSize;
  } else if (r.status == RAW_ABORTED) {
    guestUploadError = 400;
    guestClose();
  }
}
void guestStateReply() {
  portENTER_CRITICAL(&stepMux);
  GuestState s = guestState;
  portEXIT_CRITICAL(&stepMux);
  String themes = "[";
  for (int i = 0; i < 3; i++) {
    if (i) themes += ',';
    themes += '"';
    if (s.evolving) for (int j = 0; j < guestThemes.count[i]; j++) {
      if (j) themes += ',';
      themes += guestThemes.id[i][j];
    }
    themes += '"';
  }
  themes += ']';
  char out[340];
  snprintf(out, sizeof out, "{\"partProtocol\":2,\"rev\":\"%lu\",\"peopleRev\":\"%lu\",\"photo\":%s,\"known\":%s,\"pending\":%s,\"evolving\":%s,\"hold\":%lu,\"slots\":[\"%s\",\"%s\",\"%s\"],\"themes\":",
           (unsigned long)s.rev, (unsigned long)peopleRev, s.photo ? "true" : "false", s.known ? "true" : "false", s.pending ? "true" : "false",
           s.evolving ? "true" : "false", (unsigned long)guestHoldS, s.slots[0], s.slots[1], s.slots[2]);
  server.sendHeader("Cache-Control","no-store");
  server.send(200, "application/json", String(out) + themes + "}");
}
void guestFail(int code, const char* why) { guestClose(); reply(code, why); }

bool guestSlots(const String& text, char slots[3][41]) {
  int slot = 0, n = 0;
  for (unsigned i = 0; i < text.length(); i++) {
    char c = text[i];
    if (c == ',') {
      if (++slot >= 3) return false;
      n = 0;
    } else {
      if (n >= 40 || !(isalnum((unsigned char)c) || c == '-' || c == '_')) return false;
      slots[slot][n++] = c;
    }
  }
  return slot == 2;
}
// A count boundary is mandatory on every guest scene request. In particular, a
// cached page that still submits a local erase cannot start the old operation.
bool guestCounts(const String& value, uint16_t parts[3]) {
  int slot=0; bool digits=false;
  for (unsigned j=0; j<value.length(); j++) {
    char c=value[j];
    if (c==',') {
      if (!digits || ++slot>=3) return false;
      digits=false;
    } else {
      if (c<'0' || c>'9') return false;
      int n=parts[slot]*10+(c-'0');
      if (n>MAXPTS) return false;
      parts[slot]=n; digits=true;
    }
  }
  return slot==2 && digits;
}
// Slots are separate steps, so a detailed photo in each of the three places can
// use the full per-pattern buffer. They return to their own rim gates and the
// next path starts at its nearest equivalent turn on the same rim.
void queueGuestDrawing(const char slots[][41], bool fresh, bool photo, bool generated, int addSlot=-1) {
  Step batch[5]={}; int num=0;
  if (fresh) {
    if (rehomeOn) batch[num++].kind=SK_REHOME;
    batch[num].kind=SK_GEN;
    batch[num++].g=eraseP(true,EPITCH);
  }
  if (photo) batch[num++].kind=SK_GUEST;
  else for (int i=0;i<3;i++) if (slots[i][0] && (addSlot<0 || i==addSlot)) {
    batch[num].kind=SK_GUEST; batch[num++].guestSlot=i+1;
  }
  batch[num-1].guestLast=true;
  portENTER_CRITICAL(&stepMux);
  memcpy(nextGuestSlots,slots,sizeof nextGuestSlots);
  if (!generated) guestState.evolving=false;
  nextGuestIsScene=!photo;
  guestState.pending=true; guestState.photo=false; guestState.known=false; guestState.rev++;
  for (int i=0;i<num;i++) { batch[i].guest=true; steps[stepN++]=batch[i]; }
  portEXIT_CRITICAL(&stepMux);
}
void getGuestPart() {
  String where=server.arg("slot");
  if (where.length()!=1 || where[0]<'0' || where[0]>'2') { reply(400,"Invalid guest place."); return; }
  int i=where[0]-'0';
  if (!guestState.known || guestState.pending || server.arg("rev")!=String((unsigned long)guestState.rev)) {
    reply(409,"The scene has changed."); return;
  }
  if (!guestState.slots[i][0]) { reply(404,"That place is empty."); return; }
  File f=openGuestSlot(i,guestFiles[i].bank,"r");
  if (!f || f.size()!=guestFiles[i].count*sizeof(Pt)) { reply(500,"Stored drawing unavailable."); return; }
  server.sendHeader("Cache-Control","no-store");
  server.streamFile(f,"application/octet-stream");
}
void guestDone() {
  if (guestUploadError || !guestLocked) {
    guestFail(guestUploadError ? guestUploadError : 400, guestUploadError==409 ? "The table is busy or needs to find home." : "Could not receive the drawing.");
    return;
  }
  String mode = server.header("X-Guest-Mode");
  bool edit = mode == "edit", photo = mode == "photo";
  char slots[3][41] = {};
  if ((!photo && !edit && mode != "fresh") || !guestSlots(server.header("X-Guest-Slots"), slots)) {
    guestFail(400, "Invalid drawing mode or subjects."); return;
  }
  if (server.header("X-Guest-Rev") != String((unsigned long)guestState.rev) || (edit && !guestState.known) ||
      busy() || stepN || autoOn || bootPending || !homed || fault) {
    guestFail(409, "The sand has changed. Refresh the preview."); return;
  }
  int changed = 0, used = 0, editedSlot = -1;
  for (int i=0; i<3; i++) {
    if (slots[i][0]) used++;
    if (strcmp(slots[i],guestState.slots[i])) { changed++; editedSlot = i; }
  }
  if ((photo && used) || (!photo && !used) || (edit && changed!=1)) {
    guestFail(400, "An edit changes one subject."); return;
  }
  if (guestBytes%sizeof(Pt)) { guestFail(400,"Incomplete drawing point."); return; }
  long n=guestBytes/sizeof(Pt);
  if (photo) {
    if (!validGuestPath(guestFile,0,n,-1,true)) { guestFail(400,"Invalid portrait path."); return; }
    if (!guestFile.seek(0) || guestFile.read((uint8_t*)pat,guestBytes)!=guestBytes) {
      patN=0; guestFail(500,"Could not load the portrait."); return;
    }
    patN=n; queueGuestDrawing(slots,true,true,false);
  } else {
    uint16_t parts[3]={};
    if (!guestCounts(server.header("X-Guest-Counts"),parts) || parts[0]+parts[1]+parts[2]!=n) {
      guestFail(400,"This page needs updating. Reload the guest page and preview again."); return;
    }
    GuestSlotFile staged[3];
    memcpy(staged,guestFiles,sizeof staged);
    uint32_t offset=0;
    for (int i=0;i<3;i++) {
      bool supplied=(!edit || i==editedSlot) && slots[i][0];
      if (supplied!=(parts[i]!=0) || (edit && i==editedSlot && !supplied)) {
        guestFail(400,"The drawing does not match its places."); return;
      }
      if (!slots[i][0]) staged[i]={};
      if (!supplied) continue;
      if (!validGuestPath(guestFile,offset,parts[i],i,false)) { guestFail(400,"Invalid path for this place."); return; }
      if (!stageGuestSlot(guestFile,offset,i,parts[i],staged[i])) { guestFail(507,"Could not store the subject."); return; }
      offset+=parts[i]*sizeof(Pt);
    }
    double th,rho; modelPolar(c1,c2,th,rho,nullptr);
    bool addOnly=edit && !guestState.slots[editedSlot][0];
    if (addOnly && (rho<.997 || (rehomeOn && unchecked>=MAX_UNCHECKED))) {
      guestFail(409,"This place can only be filled from the rim after a position check. Start a new scene to clear the table."); return;
    }
    if (!guestFilesReady(staged,slots)) { guestFail(500,"Could not recover every subject; the sand is unchanged."); return; }
    memcpy(guestFiles,staged,sizeof guestFiles);
    queueGuestDrawing(slots,!addOnly,false,false,addOnly ? editedSlot : -1);
  }
  guestClose();
  guestStateReply();
}
