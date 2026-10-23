// bridge_config.hpp - the tests' inline configs in their short form.
//
// Many tests write a config with one network the short way: "adapter",
// "master", "nodes" (and "links", "interface", "bitrate") at the top, the way
// version 1 files were. canworks reads only version 2 bridge configs, so
// as_bridge_config() turns such a text into one: the network goes into
// networks[0], master.diagnostics and master.cia309 move to the top, and a
// config without "bridge" or "codesys" gets a local bridge object. A text
// that is already a version 2 config only gets the bridge object; a text
// that is not JSON comes back unchanged.

#ifndef BRIDGE_CONFIG_HPP
#define BRIDGE_CONFIG_HPP

#include <cstdlib>
#include <string>

#include "cJSON.h"

namespace test_config {

inline std::string as_bridge_config(const std::string& text) {
  cJSON* in = cJSON_Parse(text.c_str());
  if (!cJSON_IsObject(in)) {
    cJSON_Delete(in);
    return text;
  }
  const cJSON* version = cJSON_GetObjectItemCaseSensitive(in, "schema_version");
  const bool short_form = !cJSON_GetObjectItemCaseSensitive(in, "networks") &&
                          (!version || (cJSON_IsNumber(version) && version->valuedouble == 1));
  cJSON* out = in;
  if (short_form) {
    out = cJSON_CreateObject();
    cJSON* net = cJSON_CreateObject();
    cJSON* adapter = nullptr;
    cJSON* top_extra = cJSON_CreateObject();
    while (in->child) {
      cJSON* item = cJSON_DetachItemViaPointer(in, in->child);
      std::string key = item->string ? item->string : "";
      if (key == "schema_version") {
        cJSON_Delete(item);
      } else if (key == "interface" || key == "bitrate") {
        if (!adapter) adapter = cJSON_CreateObject();
        cJSON_AddItemToObject(adapter, key.c_str(), item);
      } else if (key == "master") {
        for (const char* moved : {"diagnostics", "cia309"})
          if (cJSON* m = cJSON_DetachItemFromObjectCaseSensitive(item, moved)) cJSON_AddItemToObject(top_extra, moved, m);
        cJSON_AddItemToObject(net, "master", item);
      } else if (key == "adapter" || key == "nodes" || key == "links" || key == "name") {
        cJSON_AddItemToObject(net, key.c_str(), item);
      } else {
        cJSON_AddItemToObject(top_extra, key.c_str(), item);
      }
    }
    cJSON_Delete(in);
    if (adapter) {
      cJSON* a = cJSON_GetObjectItemCaseSensitive(net, "adapter");
      if (cJSON_IsObject(a)) {
        while (adapter->child) {
          cJSON* item = cJSON_DetachItemViaPointer(adapter, adapter->child);
          cJSON_DeleteItemFromObjectCaseSensitive(a, item->string);
          cJSON_AddItemToObject(a, item->string, item);
        }
        cJSON_Delete(adapter);
      } else {
        cJSON_AddItemToObject(net, "adapter", adapter);
      }
    }
    cJSON_AddNumberToObject(out, "schema_version", 2);
    while (top_extra->child) {
      cJSON* item = cJSON_DetachItemViaPointer(top_extra, top_extra->child);
      cJSON_AddItemToObject(out, item->string, item);
    }
    cJSON_Delete(top_extra);
    cJSON* nets = cJSON_CreateArray();
    cJSON_AddItemToArray(nets, net);
    cJSON_AddItemToObject(out, "networks", nets);
  }
  if (!cJSON_GetObjectItemCaseSensitive(out, "bridge") && !cJSON_GetObjectItemCaseSensitive(out, "codesys"))
    cJSON_AddItemToObject(out, "bridge",
                          cJSON_Parse(R"({"listen": "127.0.0.1:1502", "writers": ["127.0.0.1"]})"));
  char* printed = cJSON_Print(out);
  std::string result = printed;
  std::free(printed);
  cJSON_Delete(out);
  return result;
}

}  // namespace test_config

#endif  // BRIDGE_CONFIG_HPP
