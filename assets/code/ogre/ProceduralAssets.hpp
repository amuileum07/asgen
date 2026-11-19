#pragma once

// OGRE Classic 1.12/14: call after Root/SceneManager/render-system setup.
// PGEO stores little-endian floats. No XML converter or JSON library needed.
#include <Ogre.h>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace ProceduralAssets {
inline void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
inline std::uint32_t readU32(std::istream& stream) {
    unsigned char b[4]{};
    stream.read(reinterpret_cast<char*>(b), 4);
    require(bool(stream), "Truncated procedural asset");
    return std::uint32_t(b[0]) | (std::uint32_t(b[1]) << 8) |
           (std::uint32_t(b[2]) << 16) | (std::uint32_t(b[3]) << 24);
}
inline float readFloat(std::istream& stream) {
    static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
    const auto bits = readU32(stream);
    float value{};
    std::memcpy(&value, &bits, 4);
    require(std::isfinite(value), "Nonfinite procedural vertex");
    return value;
}
inline void checkMagic(std::istream& stream, const char* prefix) {
    char header[8]{};
    stream.read(header, 8);
    require(bool(stream) && std::memcmp(header, prefix, 4) == 0 &&
            header[4] == 1 && header[5] == 0 && header[6] == 0 && header[7] == 0,
            "Unsupported procedural asset version");
}
inline std::filesystem::path assetPath(const std::filesystem::path& root,
                                     const std::string& relative) {
    std::filesystem::path path(relative);
    require(!path.is_absolute(), "Absolute path in procedural scene");
    for (const auto& part : path)
        require(part != "..", "Parent path in procedural scene");
    return root / path;
}

inline Ogre::MeshPtr loadGeometry(Ogre::SceneManager& scene,
                                 const std::filesystem::path& path,
                                 const std::string& resource,
                                 const std::string& group) {
    auto cached = Ogre::MeshManager::getSingleton().getByName(resource, group);
    if (cached) return cached;
    std::ifstream stream(path, std::ios::binary);
    require(bool(stream), "Cannot open procedural geometry");
    checkMagic(stream, "PGEO");
    const auto sections = readU32(stream);
    require(sections > 0 && sections < 4096, "Invalid section count");
    auto* object = scene.createManualObject(resource + "_bake");
    try {
        for (std::uint32_t section = 0; section < sections; ++section) {
            unsigned char lengthBytes[2]{};
            stream.read(reinterpret_cast<char*>(lengthBytes), 2);
            const auto length = unsigned(lengthBytes[0]) + unsigned(lengthBytes[1]) * 256;
            require(length > 0 && length < 4096, "Invalid material length");
            std::string material(length, '\0');
            stream.read(material.data(), length);
            const auto vertices = readU32(stream), indices = readU32(stream);
            require(vertices > 0 && vertices < 20000000 && indices < 100000000 &&
                    indices % 3 == 0, "Invalid procedural buffer counts");
            object->estimateVertexCount(vertices);
            object->estimateIndexCount(indices);
            object->begin(material, Ogre::RenderOperation::OT_TRIANGLE_LIST, group);
            for (std::uint32_t i = 0; i < vertices; ++i) {
                std::array<float, 12> v{};
                for (auto& value : v) value = readFloat(stream);
                object->position(v[0], v[1], v[2]);
                object->normal(v[3], v[4], v[5]);
                object->textureCoord(v[6], v[7]);
                object->colour(v[8], v[9], v[10], v[11]);
            }
            for (std::uint32_t i = 0; i < indices; ++i) {
                const auto index = readU32(stream);
                require(index < vertices, "Invalid procedural triangle index");
                object->index(index);
            }
            object->end();
        }
        auto mesh = object->convertToMesh(resource, group);
#if OGRE_VERSION_MAJOR >= 14
        mesh->buildTangentVectors(0, false, false, true);
#else
        mesh->buildTangentVectors(Ogre::VES_TANGENT, 0, 0, false, false, true);
#endif
        scene.destroyManualObject(object);
        return mesh;
    } catch (...) {
        scene.destroyManualObject(object);
        throw;
    }
}

inline void loadScene(const std::filesystem::path& directory,
                      Ogre::SceneManager& scene, Ogre::SceneNode& parent,
                      const std::string& prefix = "Town_",
                      const std::string& group = "ProceduralTown") {
    auto& resources = Ogre::ResourceGroupManager::getSingleton();
    if (!resources.resourceGroupExists(group)) resources.createResourceGroup(group);
    resources.addResourceLocation(directory.string(), "FileSystem", group, true);
    resources.initialiseResourceGroup(group);
    std::ifstream input(directory / "settlement.tsv");
    require(bool(input), "Cannot open procedural scene");
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line.front() == '#') continue;
        std::istringstream row(line);
        std::vector<std::string> fields;
        std::string field;
        while (std::getline(row, field, '\t')) fields.push_back(field);
        require(fields.size() == 12, "Invalid procedural node");
        std::array<float, 10> v{};
        for (unsigned i = 0; i < v.size(); ++i) {
            v[i] = std::stof(fields[i + 2]);
            require(std::isfinite(v[i]), "Invalid procedural transform");
        }
        const auto resource = "ProcGeometry/" + fields[1];
        auto mesh = loadGeometry(scene, assetPath(directory, fields[1] + ".ogregeom"),
                                 resource, group);
        auto* entity = scene.createEntity(prefix + fields[0], mesh->getName(), group);
        auto* node = parent.createChildSceneNode(prefix + fields[0]);
        node->setPosition(v[0], v[1], v[2]);
        node->setOrientation(Ogre::Quaternion(v[3], v[4], v[5], v[6]));
        node->setScale(v[7], v[8], v[9]);
        node->attachObject(entity);
    }
}

struct AssetMarker {
    std::string id, kind, variant;
    Ogre::Vector3 position, size;
    Ogre::Quaternion orientation;
};
inline std::vector<AssetMarker> loadAssetMarkers(const std::filesystem::path& directory) {
    std::ifstream input(directory / "asset_markers.tsv");
    std::vector<AssetMarker> result;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line.front() == '#') continue;
        std::istringstream row(line);
        AssetMarker marker;
        std::array<float, 10> v{};
        row >> marker.id >> marker.kind;
        for (auto& value : v) row >> value;
        row >> marker.variant;
        require(bool(row), "Invalid asset marker");
        for (auto value : v) require(std::isfinite(value), "Nonfinite asset marker");
        marker.position = Ogre::Vector3(v[0], v[1], v[2]);
        marker.orientation = Ogre::Quaternion(v[3], v[4], v[5], v[6]);
        marker.size = Ogre::Vector3(v[7], v[8], v[9]);
        result.push_back(marker);
    }
    return result;
}

// Optional night lighting; load only the lights needed by the active area.
inline std::size_t loadStreetLights(const std::filesystem::path& directory,
                                   Ogre::SceneManager& scene, Ogre::SceneNode& parent,
                                   const std::string& prefix = "TownLight_") {
    std::ifstream input(directory / "street_lights.tsv");
    std::string line, id;
    std::size_t count = 0;
    while (std::getline(input, line)) {
        if (line.empty() || line.front() == '#') continue;
        std::istringstream row(line);
        std::array<float, 7> v{};
        row >> id;
        for (auto& value : v) row >> value;
        require(bool(row) && v[6] > 0, "Invalid street light");
        for (auto value : v) require(std::isfinite(value), "Nonfinite street light");
        auto* light = scene.createLight(prefix + id);
        light->setType(Ogre::Light::LT_POINT);
        light->setDiffuseColour(v[3], v[4], v[5]);
        light->setSpecularColour(v[3], v[4], v[5]);
        light->setAttenuation(v[6], 1, 4.5f / v[6], 75.0f / (v[6] * v[6]));
        auto* node = parent.createChildSceneNode(prefix + id);
        node->setPosition(v[0], v[1], v[2]);
        node->attachObject(light);
        ++count;
    }
    return count;
}

struct CollisionBuffers {
    std::vector<float> positions;             // xyz, 12-byte stride
    std::vector<std::uint32_t> indices;        // triangle list
};
inline CollisionBuffers loadCollision(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    require(bool(stream), "Cannot open procedural collision mesh");
    checkMagic(stream, "PCOL");
    const auto vertices = readU32(stream), triangles = readU32(stream);
    require(vertices < 20000000 && triangles < 50000000, "Invalid collision counts");
    CollisionBuffers result;
    result.positions.resize(std::size_t(vertices) * 3);
    result.indices.resize(std::size_t(triangles) * 3);
    for (auto& value : result.positions) value = readFloat(stream);
    for (auto& index : result.indices) {
        index = readU32(stream);
        require(index < vertices, "Invalid collision index");
    }
    return result;
}
} // namespace ProceduralAssets
