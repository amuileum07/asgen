#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <optional>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace MedievalAtlas {

struct Position { float x{}, y{}, z{}; };  // OGRE axes, metres.
using Cell = std::pair<int, int>;

inline void expect(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
inline float clamp(float x, float lo = 0, float hi = 1) {
    return std::clamp(x, lo, hi);
}
inline float lerp(float a, float b, float t) { return a + (b - a) * t; }
inline float smooth(float a, float b, float x) {
    const float t = clamp((x - a) / (b - a));
    return t * t * (3 - 2 * t);
}
inline std::vector<std::string> fields(const std::string& line) {
    std::vector<std::string> out;
    std::istringstream stream(line);
    std::string part;
    while (std::getline(stream, part, '\t')) out.push_back(part);
    return out;
}
inline float number(const std::string& s) {
    std::size_t count = 0;
    const float x = std::stof(s, &count);
    expect(count == s.size() && std::isfinite(x), "Invalid atlas number");
    return x;
}
inline std::uint32_t word(std::istream& stream) {
    unsigned char bytes[4]{};
    stream.read(reinterpret_cast<char*>(bytes), 4);
    expect(bool(stream), "Truncated atlas terrain");
    return std::uint32_t(bytes[0]) | (std::uint32_t(bytes[1]) << 8) |
           (std::uint32_t(bytes[2]) << 16) | (std::uint32_t(bytes[3]) << 24);
}
inline float single(std::istream& stream) {
    const auto bits = word(stream);
    float v{};
    std::memcpy(&v, &bits, 4);
    expect(std::isfinite(v), "Invalid atlas terrain height");
    return v;
}

struct Ground {
    float height{}, level{};
    std::uint8_t biome{}, water{};
};

class Terrain {
public:
    explicit Terrain(const std::filesystem::path& file) {
        std::ifstream stream(file, std::ios::binary);
        char magic[8]{};
        stream.read(magic, 8);
        expect(bool(stream) && std::memcmp(magic, "PTIL\2\0\0\0", 8) == 0,
               "Unsupported atlas terrain");
        width_ = word(stream);
        depth_ = word(stream);
        left_ = single(stream);
        bottom_ = single(stream);
        step_ = single(stream);
        expect(width_ >= 2 && width_ <= 4097 && depth_ >= 2 && depth_ <= 4097 &&
               step_ >= 4 && step_ <= 64, "Invalid atlas terrain extent");
        values_.reserve(std::size_t(width_) * depth_);
        for (std::size_t n = 0; n < std::size_t(width_) * depth_; ++n) {
            Ground sample{single(stream), single(stream)};
            const auto meta = word(stream);
            sample.biome = std::uint8_t(meta);
            sample.water = std::uint8_t(meta >> 8);
            expect(sample.biome < 8 && sample.water <= 3, "Invalid terrain class");
            values_.push_back(sample);
        }
        expect(stream.peek() == std::char_traits<char>::eof(),
               "Unexpected terrain bytes");
    }

    float step() const { return step_; }

    Ground sample(float x, float z) const {
        const float u = clamp((x - left_) / step_, 0, float(width_ - 1));
        const float v = clamp((-z - bottom_) / step_, 0, float(depth_ - 1));
        const auto i = std::min(std::uint32_t(u), width_ - 2);
        const auto j = std::min(std::uint32_t(v), depth_ - 2);
        const auto at = [&](unsigned a, unsigned b) {
            return values_[std::size_t(b)*width_ + a];
        };
        const auto a = at(i, j), b = at(i+1, j), c = at(i+1, j+1), d = at(i, j+1);
        const float s = u - i, t = v - j;
        const auto triangle = [&](float aa, float bb, float cc, float dd) {
            return s >= t ? aa + (bb-aa)*s + (cc-bb)*t
                          : aa + (cc-dd)*s + (dd-aa)*t;
        };
        auto nearest = at(std::uint32_t(std::round(u)), std::uint32_t(std::round(v)));
        nearest.height = triangle(a.height, b.height, c.height, d.height);
        if (a.water && b.water && c.water && d.water)
            nearest.level = triangle(a.level, b.level, c.level, d.level);
        return nearest;
    }

private:
    std::uint32_t width_{}, depth_{};
    float left_{}, bottom_{}, step_{};
    std::vector<Ground> values_;
};

struct Climate {
    float elevation{}, fog{}, retention{}, exposure{};
    std::string biome, weather, water;
    std::array<float, 12> temperature{}, rainfall{};
};
struct Weather {
    float temperature{}, precipitation{}, wetness{}, snow{}, fog{}, daylight{};
    float windX{}, windZ{}, iceMetres{}, waterOffset{};
    bool iceSupports{}, dusty{};
};
struct Surface {
    Ground ground;
    Weather atmosphere;
    float support{};
    float traction{1.f};
    bool swimmable{};
};
struct Trail {
    std::string from, to, condition;
    float metres{};
    std::optional<Position> gate;
};
struct RoadSpan {
    Position a, b;
    float width{};
    bool bridge{};
};
struct Dungeon {
    std::string kind, seal;
    Position entrance;
};
struct WaterBody {
    std::string kind, outlet;
    float depth{}, salinity{};
    bool seasonal{};
};
struct Interaction {
    std::string id, kind, seal;
    Position position, size;
};
struct Press { Position foot; float radius{}, remaining{}; };

inline std::vector<Interaction> loadInteractions(const std::filesystem::path& tile) {
    std::vector<Interaction> result;
    std::ifstream input(tile / "interactions.tsv");
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line.front() == '#') continue;
        const auto f = fields(line);
        expect(f.size() == 9, "Invalid interaction row");
        result.push_back({f[0], f[1], f[8],
            {number(f[2]), number(f[3]), number(f[4])},
            {number(f[5]), number(f[6]), number(f[7])}});
    }
    return result;
}

class World {
public:
    explicit World(const std::filesystem::path& root)
        : root_(root), terrain_(root / "terrain.ptil") {
        std::ifstream stream(root / "atlas.tsv");
        std::string line;
        expect(bool(std::getline(stream, line)), "Cannot open atlas index");
        auto header = fields(line);
        expect(header.size() == 6 && header[0] == "ATLAS" && header[1] == "2",
               "Unsupported atlas index");
        seed_ = std::stoul(header[2]);
        width_ = std::stoi(header[3]);
        depth_ = std::stoi(header[4]);
        tile_ = std::stoi(header[5]);
        expect(tile_ == 256 && width_ >= tile_ && depth_ >= tile_ &&
               width_ <= 32768 && depth_ <= 32768 && width_ % tile_ == 0 &&
               depth_ % tile_ == 0, "Invalid atlas grid");
        while (std::getline(stream, line)) {
            if (!line.empty()) read(fields(line));
        }
        expect(climates_.size() == std::size_t(width_ / tile_)*(depth_ / tile_),
               "Incomplete atlas climate");
        for (const auto& t : trails_)
            expect(destinations_.count(t.from) && destinations_.count(t.to),
                   "Unknown trail endpoint");
    }

    const std::filesystem::path& root() const { return root_; }
    std::uint32_t seed() const { return seed_; }
    const Terrain& terrain() const { return terrain_; }
    const auto& destinations() const { return destinations_; }
    const auto& dungeons() const { return dungeons_; }
    const auto& waters() const { return waters_; }
    const auto& presses() const { return presses_; }
    const std::vector<RoadSpan>& roads(Cell cell) const {
        static const std::vector<RoadSpan> empty;
        const auto found=roads_.find(cell);
        return found==roads_.end()?empty:found->second;
    }
    float roadHeight(const RoadSpan& road,float t,float x,float z) const {
        const float grade=lerp(road.a.y,road.b.y,t);
        return (road.bridge?grade:std::max(grade,terrain_.sample(x,z).height))+.085f;
    }
    std::optional<float> roadSupport(Position p) const {
        std::optional<float> support;
        for (const auto& road:roads(cell(p.x,p.z))) {
            const float dx=road.b.x-road.a.x,dz=road.b.z-road.a.z;
            const float t=((p.x-road.a.x)*dx+(p.z-road.a.z)*dz)/(dx*dx+dz*dz);
            if (t<0.f || t>1.f ||
                std::hypot(p.x-road.a.x-t*dx,p.z-road.a.z-t*dz)>road.width*.5f) continue;
            const float y=roadHeight(road,t,p.x,p.z);
            if (y<=p.y+.205f && (!support || y>*support)) support=y;
        }
        return support;
    }
    double hours() const { return hour_; }
    void setHours(double time) {
        expect(std::isfinite(time) && time >= 0 && time < 1e9, "Invalid world time");
        hour_ = time;
    }
    void advance(float seconds) {
        expect(std::isfinite(seconds) && seconds >= 0, "Invalid time step");
        // Two in-world minutes per second, with real-time press recovery.
        setHours(hour_ + seconds / 30.);
        for (auto& e : presses_) e.remaining -= seconds;
        presses_.erase(
            std::remove_if(presses_.begin(), presses_.end(),
                           [](const auto& e){return e.remaining <= 0;}),
            presses_.end());
    }

    Cell cell(float x, float z) const {
        return {
            std::clamp(int(std::floor((x + width_ * .5f) / tile_)), 0, width_/tile_-1),
            std::clamp(int(std::floor((-z + depth_ * .5f) / tile_)), 0, depth_/tile_-1)
        };
    }
    bool contains(Position point) const {
        return std::abs(point.x)<width_*.5f && std::abs(point.z)<depth_*.5f;
    }
    bool roadClear(Position p,float border=1.f) const {
        for (const auto& road:roads(cell(p.x,p.z))) {
            const float dx=road.b.x-road.a.x,dz=road.b.z-road.a.z;
            const float t=clamp(((p.x-road.a.x)*dx+(p.z-road.a.z)*dz)/(dx*dx+dz*dz));
            if (std::hypot(p.x-road.a.x-t*dx,p.z-road.a.z-t*dz)<road.width*.5f+border)
                return false;
        }
        return true;
    }
    Position corner(Cell c) const {
        return {c.first*float(tile_)-width_*.5f, 0, depth_*.5f-c.second*float(tile_)};
    }
    std::map<Cell,int> visibleTiles(Position eye, int radius = 2) const {
        expect(radius >= 0 && radius <= 6, "Invalid stream radius");
        const auto [i,j] = cell(eye.x,eye.z);
        std::map<Cell,int> result;
        for (int dy = -radius; dy <= radius; ++dy) {
            for (int dx = -radius; dx <= radius; ++dx) {
                const Cell c(i+dx,j+dy);
                if (climates_.count(c))
                    result.emplace(c, std::max(std::abs(dx),std::abs(dy)) <= 1 ? 0 : 1);
            }
        }
        return result;
    }

    Weather sky(Position point, bool inside = false) const {
        const auto sample = climate(point.x, point.z);
        const float day = float(std::fmod(hour_,24.));
        const float month = float(std::fmod(hour_/(24.*30.),12.));
        const unsigned m = unsigned(month), next = (m+1)%12;
        const float seasonal = lerp(sample.temperature[m],sample.temperature[next],month-m);
        const float sun = std::sin((day-6)*.26179939f);
        const float intensity = smooth(-.13f,.56f,sun);
        Weather w;
        w.temperature = seasonal + 3.2f*std::sin((day-9)*.26179939f)
                      - .0058f*(point.y-sample.elevation);
        w.daylight = .19f + intensity*.81f;
        const float front = frontAt(point.x,point.z);
        const float averageRain = lerp(sample.rainfall[m],sample.rainfall[next],month-m);
        w.precipitation = smooth(.58f,.83f,front+clamp(averageRain/850,0,.15f));
        const float phase = std::sin(point.x*.0037f + point.z*.0051f + float(hour_)*.81f);
        w.windX = (.72f+phase*.37f)*(1+sample.exposure);
        w.windZ = (.21f+phase*.29f)*(1+sample.exposure);
        w.wetness = clamp(.26f*sample.retention+w.precipitation*.82f+front*.2f);
        w.snow = smooth(-1,4,-w.temperature)*clamp(.27f+w.precipitation*.92f);
        const float midnight = 1 - smooth(.0f,.51f,sun);
        const bool coastal = sample.weather == "SEA_FOG";
        const float pool = sample.fog*midnight*
                           (1-smooth(6,34,point.y-sample.elevation));
        w.fog = clamp(pool*.82f+w.precipitation*.24f+
                      (coastal ? midnight*front*.37f : .04f));
        if (sample.weather=="BLOWING_SNOW" && w.temperature<0)
            w.fog = std::max(w.fog, w.snow*smooth(.62f,1.2f,w.windX)*.55f);
        w.dusty = sample.weather=="DUST_GUST" && front>.62f && w.windX>.83f;
        if (w.dusty) {
            w.fog = std::max(.52f,w.fog);
            w.precipitation = 0;
        }
        const auto ground = terrain_.sample(point.x,point.z);
        const auto body = waters_.find(sample.water);
        const bool slowWater = ground.water==1 &&
            (body==waters_.end() || body->second.kind!="RIVER");
        if (slowWater) {
            const float cold = std::max(0.f,-seasonal);
            const float solarMelt = smooth(0,5,w.temperature)*.035f;
            w.iceMetres = clamp(cold*.028f-solarMelt,0,.58f);
            const float threshold = sample.temperature[next] < sample.temperature[m]
                ? .18f : .14f;
            w.iceSupports = w.iceMetres >= threshold &&
                            ground.level-ground.height > .08f;
        }
        w.waterOffset = ground.water==2 ? std::sin(float(hour_)*.5067f)*.47f
                                       : (front-.25f)*.37f;
        if (inside) {
            w.windX = w.windZ = w.precipitation = w.snow = w.fog = 0;
            w.daylight = .24f;
        }
        return w;
    }

    Surface surface(Position point) const {
        Surface s;
        s.ground = terrain_.sample(point.x,point.z);
        s.atmosphere = sky(point);
        s.support = s.ground.height;
        if (s.atmosphere.iceSupports) s.support = s.ground.level+s.atmosphere.waterOffset;
        if (s.ground.water==3 && !waterVisible("SEASONAL",s.atmosphere))
            s.ground.water=0;
        s.swimmable = s.ground.water && !s.atmosphere.iceSupports &&
                      s.ground.level+s.atmosphere.waterOffset-s.ground.height > .66f;
        if (s.ground.biome==6)
            s.traction -= .29f*smooth(.36f,.88f,s.atmosphere.wetness);
        s.traction -= .16f*s.atmosphere.snow;
        if (s.swimmable && point.y < s.ground.level+s.atmosphere.waterOffset+.22f)
            s.traction=std::min(s.traction,.63f);
        return s;
    }

    bool waterVisible(const std::string& id, const Weather& w) const {
        if (id=="SEASONAL") return w.precipitation > .37f && w.wetness > .55f;
        const auto f = waters_.find(id);
        return f==waters_.end() || !f->second.seasonal ||
            (w.precipitation > .37f && w.wetness > .55f);
    }
    bool traversable(const Trail& trail) const {
        if (trail.condition=="ALWAYS") return true;
        if (!trail.gate) return seals_.count(trail.condition)!=0;
        const auto weather = sky(*trail.gate);
        if (trail.condition=="ICE") return weather.iceSupports;
        if (trail.condition=="LOW_WATER") return weather.precipitation<.35f;
        if (trail.condition=="FERRY") return weather.fog<.64f && !weather.iceSupports;
        return false;
    }

    std::vector<std::string> route(const std::string& start,const std::string& end) const {
        if (!destinations_.count(start) || !destinations_.count(end)) return {};
        using Step = std::pair<float,std::string>;
        std::priority_queue<Step,std::vector<Step>,std::greater<Step>> todo;
        std::map<std::string,float> cost{{start,0}};
        std::map<std::string,std::string> previous;
        todo.emplace(0,start);
        while (!todo.empty()) {
            const auto [distance,id] = todo.top();
            todo.pop();
            if (id==end) break;
            if (distance>cost.at(id)) continue;
            for (const auto& edge : trails_) {
                if (edge.from!=id && edge.to!=id) continue;
                if (!traversable(edge)) continue;
                const auto& next = id==edge.from ? edge.to : edge.from;
                const float step = distance+edge.metres;
                if (!cost.count(next) || step<cost[next]) {
                    cost[next]=step;
                    previous[next]=id;
                    todo.emplace(step,next);
                }
            }
        }
        if (!cost.count(end)) return {};
        std::vector<std::string> result{end};
        while (result.back()!=start) result.push_back(previous.at(result.back()));
        std::reverse(result.begin(),result.end());
        return result;
    }

    void press(Position foot, float radius=.62f) {
        if (!presses_.empty()) {
            auto& last=presses_.back();
            if (std::hypot(last.foot.x-foot.x,last.foot.z-foot.z)<.21f) {
                last.remaining=2.8f;
                return;
            }
        }
        if (presses_.size()==8) presses_.erase(presses_.begin());
        presses_.push_back({foot,clamp(radius,.20f,2.2f),2.8f});
    }
    void activateClue(const Interaction& clue) {
        if (clue.kind=="SEAL_CLUE" && clue.seal!="-") seals_.insert(clue.seal);
    }
    std::optional<Position> triggerSeal(const std::string& dungeon) const {
        const auto d = dungeons_.find(dungeon);
        if (d==dungeons_.end() || seals_.count(d->second.seal)) return std::nullopt;
        return d->second.entrance;
    }
    std::optional<Position> returnFromRune(const std::string& seal) const {
        if (opened(seal)) return std::nullopt;
        for (const auto& [id,dungeon]:dungeons_) {
            (void)id;
            if (dungeon.seal==seal) return dungeon.entrance;
        }
        return std::nullopt;
    }
    bool claim(const Interaction& reward) {
        return reward.kind=="SEALED_RELIC" && seals_.count(reward.seal) &&
               collected_.insert(reward.id).second;
    }
    bool opened(const std::string& seal) const { return seals_.count(seal)!=0; }
    bool collected(const std::string& item) const { return collected_.count(item)!=0; }
    void recordChange(const std::string& id) {
        if (!id.empty() && id.find_first_of("\t\r\n")==std::string::npos)
            changes_.insert(id);
    }
    bool changed(const std::string& id) const { return changes_.count(id)!=0; }

    void save(std::ostream& out) const {
        out.precision(17);
        out << "ATLAS_SAVE\t1\t" << seed_ << '\t' << hour_ << '\n';
        for (const auto& id : seals_) out << "S\t" << id << '\n';
        for (const auto& id : collected_) out << "R\t" << id << '\n';
        for (const auto& id : changes_) out << "C\t" << id << '\n';
        expect(bool(out), "Could not save atlas state");
    }
    void restore(std::istream& in) {
        std::string line;
        expect(bool(std::getline(in,line)),"Missing atlas save");
        const auto header = fields(line);
        expect(header.size()==4 && header[0]=="ATLAS_SAVE" && header[1]=="1" &&
               std::stoul(header[2])==seed_,"Wrong atlas save");
        const auto savedHour=std::stod(header[3]);
        std::set<std::string> seals,collected,changes;
        while (std::getline(in,line)) {
            const auto f=fields(line);
            expect(f.size()==2,"Invalid save row");
            if (f[0]=="S") seals.insert(f[1]);
            else if (f[0]=="R") collected.insert(f[1]);
            else if (f[0]=="C") changes.insert(f[1]);
            else throw std::runtime_error("Unknown atlas save row");
        }
        setHours(savedHour);
        seals_=std::move(seals);
        collected_=std::move(collected);
        changes_=std::move(changes);
        presses_.clear();
    }

private:
    std::filesystem::path root_;
    Terrain terrain_;
    std::uint32_t seed_{};
    int width_{}, depth_{}, tile_{};
    double hour_=4372.;
    std::map<Cell,Climate> climates_;
    std::map<std::string,Position> destinations_;
    std::map<std::string,Dungeon> dungeons_;
    std::map<std::string,WaterBody> waters_;
    std::vector<Trail> trails_;
    std::map<Cell,std::vector<RoadSpan>> roads_;
    std::vector<Press> presses_;
    std::set<std::string> seals_, collected_, changes_;

    void read(const std::vector<std::string>& f) {
        if (f[0]=="T") {
            expect(f.size()==34,"Invalid climate row");
            const Cell cell(std::stoi(f[1]),std::stoi(f[2]));
            Climate c;
            c.elevation=number(f[3]);
            c.biome=f[4];
            c.weather=f[5];
            c.fog=number(f[6]);
            c.retention=number(f[7]);
            c.exposure=number(f[8]);
            c.water=f[9];
            for (unsigned n=0;n<12;++n) {
                c.temperature[n]=number(f[10+n]);
                c.rainfall[n]=number(f[22+n]);
            }
            expect(cell.first>=0 && cell.first<width_/tile_ && cell.second>=0 &&
                   cell.second<depth_/tile_ && climates_.emplace(cell,c).second,
                   "Invalid or duplicate climate cell");
        } else if (f[0]=="N") {
            expect(f.size()==6,"Invalid destination");
            destinations_.emplace(f[1],Position{number(f[2]),number(f[3]),number(f[4])});
        } else if (f[0]=="E") {
            expect(f.size()==5 || f.size()==8,"Invalid trail");
            Trail trail{f[1],f[2],f[3],number(f[4]),std::nullopt};
            if (f.size()==8) trail.gate=Position{number(f[5]),number(f[6]),number(f[7])};
            trails_.push_back(trail);
        } else if (f[0]=="D") {
            expect(f.size()==7,"Invalid dungeon");
            dungeons_.emplace(f[1],Dungeon{f[2],f[6],{number(f[3]),number(f[4]),number(f[5])}});
        } else if (f[0]=="W") {
            expect(f.size()==7,"Invalid water body");
            waters_.emplace(f[1],WaterBody{f[2],f[6],number(f[3]),number(f[4]),f[5]=="1"});
        } else if (f[0]=="R") {
            expect(f.size()==11,"Invalid road span");
            const Cell id(std::stoi(f[1]),std::stoi(f[2]));
            const RoadSpan span{{number(f[5]),number(f[6]),number(f[7])},
                {number(f[8]),number(f[9]),number(f[10])},number(f[3]),f[4]=="1"};
            expect(id.first>=0 && id.first<width_/tile_ && id.second>=0 &&
                   id.second<depth_/tile_ && span.width>0 && span.width<=16,
                   "Invalid road location or width");
            if (std::hypot(span.a.x-span.b.x,span.a.z-span.b.z)>.005f)
                roads_[id].push_back(span);
        } else {
            throw std::runtime_error("Unknown atlas record");
        }
    }

    Climate climate(float x,float z) const {
        const float u=clamp((x+width_*.5f)/tile_-.5f,0,float(width_/tile_-1));
        const float v=clamp((-z+depth_*.5f)/tile_-.5f,0,float(depth_/tile_-1));
        const int i=int(u),j=int(v);
        const auto& a=climates_.at({i,j});
        const auto& b=climates_.at({std::min(i+1,width_/tile_-1),j});
        const auto& c=climates_.at({i,std::min(j+1,depth_/tile_-1)});
        const auto& d=climates_.at({std::min(i+1,width_/tile_-1),std::min(j+1,depth_/tile_-1)});
        const auto mix=[&](float aa,float bb,float cc,float dd) {
            return lerp(lerp(aa,bb,u-i),lerp(cc,dd,u-i),v-j);
        };
        Climate out=climates_.at(cell(x,z));
        out.elevation=mix(a.elevation,b.elevation,c.elevation,d.elevation);
        out.fog=mix(a.fog,b.fog,c.fog,d.fog);
        out.retention=mix(a.retention,b.retention,c.retention,d.retention);
        out.exposure=mix(a.exposure,b.exposure,c.exposure,d.exposure);
        for (unsigned k=0;k<12;++k) {
            out.temperature[k]=mix(a.temperature[k],b.temperature[k],c.temperature[k],d.temperature[k]);
            out.rainfall[k]=mix(a.rainfall[k],b.rainfall[k],c.rainfall[k],d.rainfall[k]);
        }
        return out;
    }
    float frontAt(float x,float z) const {
        const float phase=float(seed_%5731)*.007f;
        return .50f+.29f*std::sin(x*.00072f+z*.00041f-float(hour_)*.21f+phase)
                   +.19f*std::sin(x*.00167f-z*.00212f+float(hour_)*.34f+phase);
    }
};

}  // namespace MedievalAtlas
