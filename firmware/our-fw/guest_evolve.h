// The catalog's <32sB3xII> index stays on the table. Preparation runs in the web
// task, under the flash/motion handshake. The motor task only sees the complete job.
struct GuestPoolIndex {
  char name[32];
  uint8_t slot, pad[3];
  uint32_t offset, count;
};
static_assert(sizeof(GuestPoolIndex) == 44 && sizeof(Pt) == 8, "guest pool layout");
const char* GUEST_POOL = "/lib/guest-pool.bin";

bool poolHeader(File& f, uint32_t& count) {
  char magic[4];
  return f && f.seek(0) && f.read((uint8_t*)magic,4)==4 && !memcmp(magic,"GSA1",4) &&
    f.read((uint8_t*)&count,4)==4 && count && count<=512 &&
    f.size()>=8+count*sizeof(GuestPoolIndex);
}
bool poolFind(File& f, uint32_t count, int slot, const char* id, GuestPoolIndex& entry) {
  if (!f.seek(8)) return false;
  for (uint32_t i=0;i<count;i++) {
    if (f.read((uint8_t*)&entry,sizeof entry)!=sizeof entry) return false;
    if (entry.slot!=slot || strncmp(entry.name,id,sizeof entry.name)) continue;
    return entry.name[31]==0 && entry.count>=2 && entry.count<=MAXPTS &&
      entry.offset>=8+count*sizeof entry && entry.offset<=f.size() &&
      entry.count<=(f.size()-entry.offset)/sizeof(Pt);
  }
  return false;
}

// Parse only catalog entries and verify that each proposed list actually belongs
// to the subject displayed (or currently being drawn) in that slot.
bool readGuestThemes(File& f, uint32_t count, const char slots[][41], GuestThemes& themes) {
  const char* params[]={"a","b","c"};
  bool canChange=false;
  for (int i=0;i<3;i++) {
    String list=server.arg(params[i]);
    if (!list.length()) continue;
    if (!slots[i][0] || list.length()>255 || list.endsWith(",")) return false;
    unsigned start=0;
    bool current=false;
    while (start<list.length()) {
      int end=list.indexOf(',',start);
      if (end<0) end=list.length();
      unsigned len=end-start;
      int n=themes.count[i];
      if (!len || len>=32 || n>=8) return false;
      char* id=themes.id[i][n];
      for (unsigned j=0;j<len;j++) {
        char c=list[start+j];
        if (!(isalnum((unsigned char)c) || c=='_' || c=='-')) return false;
        id[j]=c;
      }
      GuestPoolIndex e;
      if (!strcmp(id,"erase") || !poolFind(f,count,i,id,e)) return false;
      for (int j=0;j<n;j++) if (!strcmp(themes.id[i][j],id)) return false;
      if (!strcmp(slots[i],id)) current=true;
      themes.count[i]++;
      start=end+1;
    }
    if (!current) return false;
    if (themes.count[i]>1) canChange=true;
  }
  return canChange;
}

void guestEvolveRequest() {
  GuestState before;
  char slots[3][41];
  portENTER_CRITICAL(&stepMux);
  before=guestState;
  bool pendingScene=guestState.pending && nextGuestIsScene;
  memcpy(slots, pendingScene ? nextGuestSlots : guestState.slots, sizeof slots);
  portEXIT_CRITICAL(&stepMux);
  if (server.arg("rev")!=String((unsigned long)before.rev)) {
    reply(409,"The sand has changed. Refresh the scene."); return;
  }
  String on=server.arg("on");
  if (on!="1" && on!="0") { reply(400,"Choose on or off."); return; }
  unsigned long hold=300;
  GuestThemes themes={};
  if (on=="1") {
    if ((!before.known && !pendingScene) || fault || autoOn || bootPending ||
        (!pendingScene && (busy() || stepN || !homed))) {
      reply(409,"Start a guest scene first."); return;
    }
    if (server.hasArg("hold")) {
      String value=server.arg("hold"); char* end=nullptr;
      hold=strtoul(value.c_str(),&end,10);
      if (*end || hold<1 || hold>86400) { reply(400,"Hold must be 1 to 86400 seconds."); return; }
    }
    File f=LittleFS.open(GUEST_POOL,"r"); uint32_t count=0;
    if (!poolHeader(f,count)) { reply(503,"The guest variations are not installed."); return; }
    if (!readGuestThemes(f,count,slots,themes)) {
      reply(400,"Include the current subject and at least one different catalog drawing for an occupied place."); return;
    }
  }
  portENTER_CRITICAL(&stepMux);
  bool match=guestState.rev==before.rev;
  if (match) {
    if (on=="1") {
      guestThemes=themes; guestHoldS=hold; guestNextMs=millis()+hold*1000U;
    }
    guestState.evolving=(on=="1");
    guestState.rev++;
  }
  portEXIT_CRITICAL(&stepMux);
  if (!match) { reply(409,"The scene changed while saving the variations. Refresh it."); return; }
  guestStateReply();
}

void guestEvolvePoll() {
  if (!guestState.evolving || guestState.pending || !guestState.known || busy() || stepN ||
      autoOn || bootPending || restartAt || fault || !homed || (int32_t)(millis()-guestNextMs)<0) return;
  if (quietNow() || !flashBegin()) return;
  // The web task cannot receive edits during this brief read and the motion task
  // cannot start. Recheck after acquiring the claim in case a queued move won.
  if (!guestState.evolving || !guestState.known || stepN || busy() || !homed || fault ||
      (int32_t)(millis()-guestNextMs)<0) {
    flashEnd(); return;
  }
  char slots[3][41]; memcpy(slots,guestState.slots,sizeof slots);
  int eligible[3], n=0;
  for (int i=0;i<3;i++) if (guestThemes.count[i]>=2) eligible[n++]=i;
  bool ok=n>0;
  int k=ok ? eligible[rndI(0,n-1)] : 0;
  int choices[8], choicesN=0;
  for (int i=0;i<guestThemes.count[k];i++)
    if (strcmp(slots[k],guestThemes.id[k][i])) choices[choicesN++]=i;
  if (!choicesN) ok=false;
  if (ok) strlcpy(slots[k],guestThemes.id[k][choices[rndI(0,choicesN-1)]],sizeof slots[k]);
  File f=LittleFS.open(GUEST_POOL,"r"); uint32_t count=0;
  GuestPoolIndex entry;
  GuestSlotFile staged[3]; memcpy(staged,guestFiles,sizeof staged);
  ok=ok && poolHeader(f,count) && poolFind(f,count,k,slots[k],entry) &&
      stageGuestSlot(f,entry.offset,k,entry.count,staged[k]) && guestFilesReady(staged,slots);
  if (f) f.close();
  if (ok) {
    memcpy(guestFiles,staged,sizeof guestFiles);
    queueGuestDrawing(slots,true,false,true);
  } else stopGuestEvolution();
  flashEnd();
}
