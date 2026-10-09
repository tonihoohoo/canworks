#include "slave_state.h"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

#include "cJSON.h"

#ifndef CANWORKS_PREFIX
#define CANWORKS_PREFIX "/opt/canworks"
#endif

namespace canopen_plugin {

namespace {

std::string to_hex(const std::vector<uint8_t>& data) {
  static const char digits[] = "0123456789abcdef";
  std::string s;
  s.reserve(data.size() * 2);
  for (uint8_t b : data) {
    s += digits[b >> 4];
    s += digits[b & 0xF];
  }
  return s;
}

bool from_hex(const std::string& s, std::vector<uint8_t>& out) {
  if (s.size() % 2) return false;
  out.clear();
  for (size_t i = 0; i < s.size(); i += 2) {
    char buf[3] = {s[i], s[i + 1], 0};
    char* end = nullptr;
    unsigned long v = std::strtoul(buf, &end, 16);
    if (*end) return false;
    out.push_back(static_cast<uint8_t>(v));
  }
  return true;
}

bool make_dirs(const std::string& dir) {
  std::string partial;
  std::stringstream ss(dir);
  if (!dir.empty() && dir[0] == '/') partial = "/";
  for (std::string part; std::getline(ss, part, '/');) {
    if (part.empty()) continue;
    partial += part + "/";
    if (mkdir(partial.c_str(), 0755) != 0 && errno != EEXIST) return false;
  }
  return true;
}

}  // namespace

std::string default_slave_state_dir() {
  const char* env = std::getenv("CANWORKS_STATE_DIR");
  if (env && *env) return env;
  return CANWORKS_PREFIX "/state";
}

std::string slave_state_path(const std::string& dir, const std::string& network) {
  return dir + "/" + (network.empty() ? std::string("slave") : network) + ".json";
}

bool load_slave_state(const std::string& path, const std::string& eds_sha256, SlaveStore& out, std::string& note) {
  out = SlaveStore();
  note.clear();
  std::ifstream in(path, std::ios::binary);
  if (!in) return true;
  std::ostringstream ss;
  ss << in.rdbuf();
  cJSON* doc = cJSON_Parse(ss.str().c_str());
  if (!cJSON_IsObject(doc)) {
    cJSON_Delete(doc);
    note = "stored parameters in " + path + " cannot be read; starting with the EDS values";
    return false;
  }
  const cJSON* hash = cJSON_GetObjectItemCaseSensitive(doc, "eds_sha256");
  if (!cJSON_IsString(hash) || eds_sha256 != hash->valuestring) {
    cJSON_Delete(doc);
    note = "stored parameters in " + path + " were saved with another EDS; they are not applied (the EDS changed "
           "since the master saved them)";
    return false;
  }
  SlaveStore store;
  const cJSON* id = cJSON_GetObjectItemCaseSensitive(doc, "lss_node_id");
  if (cJSON_IsNumber(id) && id->valueint >= 1 && id->valueint <= 127) store.lss_id = static_cast<uint8_t>(id->valueint);
  const cJSON* saved = cJSON_GetObjectItemCaseSensitive(doc, "saved");
  const cJSON* item;
  bool ok = true;
  cJSON_ArrayForEach(item, saved) {
    std::vector<uint8_t> data;
    if (!item->string || std::strlen(item->string) != 1 || !cJSON_IsString(item) ||
        !from_hex(item->valuestring, data)) {
      ok = false;
      continue;
    }
    store.saved[item->string[0]] = data;
  }
  cJSON_Delete(doc);
  if (!ok) {
    note = "stored parameters in " + path + " cannot be read; starting with the EDS values";
    return false;
  }
  out = store;
  return true;
}

bool save_slave_state(const std::string& path, const std::string& eds_sha256, unsigned node_id,
                      const SlaveStore& store, std::string& why) {
  size_t slash = path.find_last_of('/');
  if (slash != std::string::npos && slash > 0 && !make_dirs(path.substr(0, slash))) {
    why = "cannot create " + path.substr(0, slash) + ": " + std::strerror(errno);
    return false;
  }
  cJSON* doc = cJSON_CreateObject();
  cJSON_AddStringToObject(doc, "eds_sha256", eds_sha256.c_str());
  cJSON_AddNumberToObject(doc, "node_id", node_id);
  if (store.lss_id) cJSON_AddNumberToObject(doc, "lss_node_id", store.lss_id);
  cJSON* saved = cJSON_AddObjectToObject(doc, "saved");
  for (const auto& kv : store.saved) {
    char key[2] = {kv.first, 0};
    cJSON_AddStringToObject(saved, key, to_hex(kv.second).c_str());
  }
  char* text = cJSON_Print(doc);
  cJSON_Delete(doc);
  std::string tmp = path + ".tmp";
  bool ok = false;
  {
    std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
    if (f) {
      f << text << "\n";
      f.flush();
      ok = static_cast<bool>(f);
    }
  }
  std::free(text);
  if (!ok || std::rename(tmp.c_str(), path.c_str()) != 0) {
    why = "cannot write " + path + ": " + std::strerror(errno);
    unlink(tmp.c_str());
    return false;
  }
  return true;
}

}  // namespace canopen_plugin
