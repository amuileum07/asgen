#pragma once

#include "AtlasRuntime.hpp"
#include "ProceduralAssets.hpp"
#include <OgreGpuProgramManager.h>
#include <OgreHighLevelGpuProgramManager.h>
#include <functional>

namespace MedievalAtlas {

class Collider {
public:
    explicit Collider(ProceduralAssets::CollisionBuffers data) {
        for (std::size_t i=0;i<data.indices.size();i+=3) {
            const auto read = [&](std::size_t v) {
                const auto index=data.indices[v]*3;
                return Ogre::Vector3(data.positions[index],data.positions[index+1],data.positions[index+2]);
            };
            const Tri tri{read(i),read(i+1),read(i+2)};
            const auto id=triangles_.size();
            triangles_.push_back(tri);
            const auto [minx,maxx]=std::minmax({tri.a.x,tri.b.x,tri.c.x});
            const auto [minz,maxz]=std::minmax({tri.a.z,tri.b.z,tri.c.z});
            for (int x=bin(minx);x<=bin(maxx);++x) {
                for (int z=bin(minz);z<=bin(maxz);++z)
                    buckets_[{x,z}].push_back(id);
            }
        }
    }

    std::optional<float> floor(Position p) const {
        const auto hit=buckets_.find({bin(p.x),bin(p.z)});
        if (hit==buckets_.end()) return std::nullopt;
        std::optional<float> best;
        for (auto id:hit->second) {
            const auto& tri=triangles_[id];
            const auto u=tri.b-tri.a, v=tri.c-tri.a;
            const auto normal=u.crossProduct(v);
            if (normal.y < normal.length()*.39f || normal.y<1e-5f) continue;
            const float dx=p.x-tri.a.x, dz=p.z-tri.a.z;
            const float alpha=(dz*v.x-dx*v.z)/normal.y;
            const float beta=(dx*u.z-dz*u.x)/normal.y;
            if (alpha<-.001f || beta<-.001f || alpha+beta>1.001f) continue;
            const float height=tri.a.y+alpha*u.y+beta*v.y;
            if (height<=p.y+.205f && height>p.y-1.1f && (!best || height>*best))
                best=height;
        }
        return best;
    }

    bool blocked(Position p, float radius=.33f) const {
        for (int x=bin(p.x-radius);x<=bin(p.x+radius);++x) {
            for (int z=bin(p.z-radius);z<=bin(p.z+radius);++z) {
                const auto hit=buckets_.find({x,z});
                if (hit==buckets_.end()) continue;
                for (auto id:hit->second) {
                    const auto& tri=triangles_[id];
                    const auto n=(tri.b-tri.a).crossProduct(tri.c-tri.a);
                    if (std::abs(n.y)>n.length()*.37f) continue;
                    if (std::min({tri.a.y,tri.b.y,tri.c.y}) >= p.y+1.70f ||
                        std::max({tri.a.y,tri.b.y,tri.c.y}) <= p.y+.205f) continue;
                    if (edgeDistance(p,tri.a,tri.b)<radius ||
                        edgeDistance(p,tri.b,tri.c)<radius ||
                        edgeDistance(p,tri.c,tri.a)<radius) return true;
                }
            }
        }
        return false;
    }

private:
    struct Tri { Ogre::Vector3 a,b,c; };
    std::vector<Tri> triangles_;
    std::map<Cell,std::vector<std::size_t>> buckets_;
    static int bin(float v) { return int(std::floor(v/8)); }
    static float edgeDistance(Position foot,const Ogre::Vector3& a,const Ogre::Vector3& b) {
        const float x=b.x-a.x,z=b.z-a.z,l=x*x+z*z;
        const float t=l>1e-6f?clamp(((foot.x-a.x)*x+(foot.z-a.z)*z)/l):0;
        return std::hypot(foot.x-a.x-t*x,foot.z-a.z-t*z);
    }
};

class Renderer {
public:
    Renderer(World& state, Ogre::SceneManager& scene, Ogre::SceneNode& parent)
        : world_(state),scene_(scene),parent_(parent) {
        program("AtlasVertex","atlas.vert.glsl",Ogre::GPT_VERTEX_PROGRAM);
        program("AtlasFragment","atlas.frag.glsl",Ogre::GPT_FRAGMENT_PROGRAM);
    }
    Renderer(const Renderer&)=delete;
    Renderer& operator=(const Renderer&)=delete;
    ~Renderer() {
        while (!tiles_.empty()) unload(tiles_.begin());
        if (particles_.node) release(particles_);
    }

    void update(Position eye, float seconds, bool inside=false) {
        world_.advance(seconds);
        seconds_+=seconds;
        const auto weather=world_.sky(eye,inside);
        const auto wanted=world_.visibleTiles(eye);
        for (auto it=tiles_.begin();it!=tiles_.end();) {
            if (!wanted.count(it->first)) unload(it++);
            else ++it;
        }
        for (const auto& entry:wanted)
            if (!tiles_.count(entry.first)) load(entry.first);
        const auto localLamps=lamps(eye,inside,weather.daylight);
        std::array<Ogre::Vector4,8> footprint{};
        footprint.fill(Ogre::Vector4::ZERO);
        for (std::size_t k=0;k<world_.presses().size();++k) {
            const auto& press=world_.presses()[k];
            footprint[k]=Ogre::Vector4(press.foot.x,press.foot.z,press.radius,
                                       clamp(press.remaining/2.8f));
        }
        const float day=float(std::fmod(world_.hours(),24.));
        const float turn=(day-6)*.26179939f;
        const auto sun=Ogre::Vector3(std::cos(turn),std::max(.24f,std::sin(turn)),-.60f).normalisedCopy();
        for (const auto& [id,lod]:wanted) {
            auto& tile=tiles_.at(id);
            const auto centre=world_.corner(id);
            const auto w=world_.sky({centre.x+128,eye.y,centre.z-128},inside);
            const auto waterProbe=world_.terrain().sample(centre.x+128,centre.z-128);
            for (auto& [entity,kind,water]:tile.effects) {
                entity->setVisible(
                    (lod==0 || (kind!=1 && kind!=3 && kind!=6))
                    && (kind!=4 || world_.waterVisible(water,w))
                );
            }
            for (auto& [tag,mat]:tile.materials) {
                (void)tag;
                const auto effect=mat.effect;
                for (auto* pass:mat.passes) {
                    auto v=pass->getVertexProgramParameters();
                    const float level=(effect==4) ? w.waterOffset : 0;
                    v->setNamedConstant("uMotion",Ogre::Vector4(seconds_,w.windX,w.windZ,level));
                    // Four floats per GLSL vec4.
                    v->setNamedConstant("uPress",footprint[0].ptr(),8,4);
                    auto f=pass->getFragmentProgramParameters();
                    f->setNamedConstant("uMarks",footprint[0].ptr(),8,4);
                    f->setNamedConstant("uLamps",localLamps[0].ptr(),8,4);
                    f->setNamedConstant("uAtmosphere",Ogre::Vector4(
                        weather.daylight,weather.fog,w.snow,w.wetness));
                    const float ice=effect==6?clamp(-w.temperature*.022f):w.iceMetres;
                    f->setNamedConstant("uCliff",Ogre::Vector4(waterProbe.height,seconds_,ice,
                        weather.dusty?1.f:0.f));
                    f->setNamedConstant("uSun",sun);
                }
            }
        }
        precipitation(eye,weather,inside);
    }

    std::optional<Position> tryStep(Position foot, float dx,float dz) {
        Position next{foot.x+dx,foot.y,foot.z+dz};
        if (!world_.contains(next)) return std::nullopt;
        const auto surface=world_.surface(next);
        const auto loaded=tiles_.find(world_.cell(next.x,next.z));
        std::optional<float> support;
        bool baked=false;
        // Adjacent baked precincts may own a hall spanning a tile boundary.
        for (auto& [id,tile]:tiles_) {
            (void)id;
            for (const auto& trunk:tile.trunks) {
                if (std::abs(next.y-trunk.y)<1.f &&
                    std::hypot(trunk.x-next.x,trunk.z-next.z)<trunk.w+.33f)
                    return std::nullopt;
            }
            for (const auto& item:tile.actions) {
                const auto p=item.position;
                if (item.kind=="SEAL_TRIGGER" && std::abs(next.y-p.y)<1 &&
                    std::hypot(next.x-p.x,next.z-p.z)<.53f) {
                    if (const auto home=world_.returnFromRune(item.seal)) return home;
                }
            }
            if (!tile.collider) continue;
            if (tile.collider->blocked(next)) return std::nullopt;
            if (auto floor=tile.collider->floor(next);floor && (!support || *floor>*support))
                support=floor;
        }
        baked=loaded!=tiles_.end() && bool(loaded->second.collider);
        if (!baked) {
            if (const auto deck=world_.roadSupport(next);deck && (!support || *deck>*support))
                support=deck;
        }
        if (surface.atmosphere.iceSupports && surface.support<=next.y+.205f &&
            (!support || surface.support>*support))
            support=surface.support;
        if (surface.swimmable &&
            (!support || *support < surface.ground.level-.62f) &&
            foot.y <= surface.ground.level+surface.atmosphere.waterOffset+.24f) {
            next.y=surface.ground.level+surface.atmosphere.waterOffset-.44f;
            return next;
        }
        if (!support && !baked) support=surface.ground.height;
        if (!support || *support>next.y+.205f || *support<next.y-1.1f) return std::nullopt;
        next.y=*support;
        world_.press(next);
        return next;
    }

    std::optional<Interaction> nearby(Position eye, float range=2.7f) const {
        std::optional<Interaction> found;
        for (const auto& [id,tile]:tiles_) {
            (void)id;
            for (const auto& item:tile.actions) {
                if (item.kind=="SEAL_TRIGGER" || item.kind=="DUNGEON_LAMP" ||
                    item.kind=="STREET_LIGHT") continue;
                const auto p=item.position;
                const float dist=std::hypot(p.x-eye.x,p.y-eye.y,p.z-eye.z);
                if (dist<range) {
                    found=item;
                    range=dist;
                }
            }
        }
        return found;
    }

private:
    struct Material {
        int effect{};
        Ogre::MaterialPtr ptr;
        std::vector<Ogre::Pass*> passes;
    };
    struct Tile {
        std::string group;
        Ogre::SceneNode* node{};
        std::vector<Ogre::Entity*> entities;
        std::vector<Ogre::ManualObject*> manual;
        std::vector<std::tuple<Ogre::MovableObject*,int,std::string>> effects;
        std::map<std::string,Material> materials;
        std::unique_ptr<Collider> collider;
        std::vector<Interaction> actions;
        std::vector<Interaction> lamps;
        std::vector<Ogre::Vector4> trunks;
    };
    World& world_;
    Ogre::SceneManager& scene_;
    Ogre::SceneNode& parent_;
    float seconds_{};
    std::map<Cell,Tile> tiles_;
    Tile particles_;

    std::array<Ogre::Vector4,8> lamps(Position eye,bool inside,float daylight) const {
        std::array<Ogre::Vector4,8> result{};
        result.fill(Ogre::Vector4::ZERO);
        if (!inside && daylight>.78f) return result;
        std::vector<std::pair<float,Ogre::Vector4>> nearest;
        for (const auto& [id,tile]:tiles_) {
            (void)id;
            for (const auto& lamp:tile.lamps) {
                if ((lamp.kind=="DUNGEON_LAMP")!=inside) continue;
                const auto p=lamp.position;
                const float range=inside?3.8f:7.6f;
                const float distance=std::hypot(p.x-eye.x,p.y-eye.y,p.z-eye.z);
                if (distance<range*3) nearest.emplace_back(distance,Ogre::Vector4(p.x,p.y,p.z,range));
            }
        }
        std::sort(nearest.begin(),nearest.end(),[](const auto& a,const auto& b){return a.first<b.first;});
        for (std::size_t i=0;i<std::min(result.size(),nearest.size());++i)
            result[i]=nearest[i].second;
        return result;
    }

    static int effectType(const std::string& kind) {
        if (kind=="GRASS") return 1;
        if (kind=="CROWN") return 2;
        if (kind=="FLAG") return 3;
        if (kind=="WATER") return 4;
        if (kind=="LAMP") return 5;
        if (kind=="FOUNTAIN") return 6;
        return 0;
    }
    void program(const std::string& name, const char* file, Ogre::GpuProgramType type) {
        auto& resources=Ogre::ResourceGroupManager::getSingleton();
        if (!resources.resourceGroupExists("AtlasShaders")) resources.createResourceGroup("AtlasShaders");
#if OGRE_VERSION_MAJOR >= 14
        auto& mgr=Ogre::GpuProgramManager::getSingleton();
#else
        auto& mgr=Ogre::HighLevelGpuProgramManager::getSingleton();
#endif
        if (mgr.getByName(name,"AtlasShaders")) return;
        std::ifstream source(world_.root()/"ogre"/file);
        expect(bool(source),"Missing atlas shader");
        std::ostringstream shader;
        shader<<source.rdbuf();
        auto prog=mgr.createProgram(name,"AtlasShaders","glsl",type);
        prog->setSource(shader.str());
        prog->load();
        expect(prog->isSupported(),"Atlas shader needs OpenGL 3.3");
    }
    void bind(Ogre::Pass& pass,int effect,bool paint,bool outline,bool roof) {
        using Auto=Ogre::GpuProgramParameters;
        pass.setLightingEnabled(false);
        pass.setVertexProgram("AtlasVertex");
        pass.setFragmentProgram("AtlasFragment");
        auto v=pass.getVertexProgramParameters();
        v->setNamedAutoConstant("uWorld",Auto::ACT_WORLD_MATRIX);
        v->setNamedAutoConstant("uNormal",Auto::ACT_INVERSE_TRANSPOSE_WORLD_MATRIX);
        v->setNamedAutoConstant("uViewProj",Auto::ACT_VIEWPROJ_MATRIX);
        v->setNamedAutoConstant("uEye",Auto::ACT_CAMERA_POSITION);
        v->setNamedAutoConstant("uViewport",Auto::ACT_VIEWPORT_SIZE);
        v->setNamedConstant("uEffect",effect);
        v->setNamedConstant("uOutline",outline?.88f:0.f);
        auto f=pass.getFragmentProgramParameters();
        f->setNamedAutoConstant("uEye",Auto::ACT_CAMERA_POSITION);
        f->setNamedConstant("uEffect",effect);
        f->setNamedConstant("uBase",pass.getDiffuse());
        f->setNamedConstant("uPaint",int(paint));
        f->setNamedConstant("uRoof",int(roof));
        f->setNamedConstant("uTextured",int(pass.getNumTextureUnitStates()>0));
        f->setNamedConstant("uTexture",0);
        f->setNamedConstant("uLine",outline?Ogre::Vector4(.066,.084,.109,1):Ogre::Vector4::ZERO);
        if (effect==1 || effect==3) pass.setCullingMode(Ogre::CULL_NONE);
        if (effect==7) {
            pass.setCullingMode(Ogre::CULL_NONE);
            pass.setDepthWriteEnabled(false);
            pass.setSceneBlending(Ogre::SBT_TRANSPARENT_ALPHA);
        }
        if (outline) {
            pass.setCullingMode(Ogre::CULL_ANTICLOCKWISE);
            pass.setDepthWriteEnabled(false);
        }
    }
    Ogre::MaterialPtr material(Tile& tile,const Ogre::MaterialPtr& source,
                               int effect,bool outline,bool forcePaint=false) {
        const std::string key=source->getName()+"_"+std::to_string(effect)+(outline?"_ink":"");
        if (tile.materials.count(key)) return tile.materials.at(key).ptr;
        auto copy=source->clone(tile.group+"_"+key,true,tile.group);
        auto* technique=copy->getTechnique(0);
        auto* base=technique->getPass(0);
        const bool paint=forcePaint ||
            (base->getVertexColourTracking() & Ogre::TVC_DIFFUSE)!=0;
        const bool roof=source->getName().rfind("Proc/Roof/",0)==0;
        bind(*base,effect,paint,false,roof);
        Material stylized{effect,copy,{base}};
        if (outline) {
            auto* ink=technique->createPass();
            bind(*ink,effect,paint,true,false);
            stylized.passes.push_back(ink);
        }
        tile.materials.emplace(key,std::move(stylized));
        return copy;
    }
    void attach(Tile& tile,const std::filesystem::path& directory,
                const char* filename,bool effectLayer) {
        std::ifstream stream(directory/filename);
        expect(bool(stream)||effectLayer,"Missing atlas model layer");
        std::string line;
        while (std::getline(stream,line)) {
            if (line.empty() || line.front()=='#') continue;
            const auto row=fields(line);
            expect(row.size()==(effectLayer?14:12),"Invalid atlas scene node");
            const auto mesh=ProceduralAssets::loadGeometry(scene_,
                ProceduralAssets::assetPath(directory,row[1]+".ogregeom"),
                tile.group+"/"+row[1],tile.group);
            auto* entity=scene_.createEntity(tile.group+"_"+row[0],mesh->getName(),tile.group);
            auto* node=tile.node->createChildSceneNode();
            node->setPosition(number(row[2]),number(row[3]),number(row[4]));
            node->setOrientation(Ogre::Quaternion(number(row[5]),number(row[6]),number(row[7]),number(row[8])));
            node->setScale(number(row[9]),number(row[10]),number(row[11]));
            node->attachObject(entity);
            tile.entities.push_back(entity);
            const int kind=effectLayer?effectType(row[12]):0;
            const bool ink=mesh->getBoundingSphereRadius()>=4.f &&
                           mesh->getBoundingSphereRadius()<22.f;
            for (auto* part:entity->getSubEntities())
                part->setMaterial(material(tile,part->getMaterial(),kind,ink && !effectLayer));
            if (effectLayer) {
                tile.effects.emplace_back(entity,kind,row[13]);
                entity->setCastShadows(false);
            }
        }
    }
    Ogre::ManualObject* manual(Tile& tile,const std::string& name,
                               const Ogre::MaterialPtr& mat) {
        auto* mesh=scene_.createManualObject(tile.group+"_"+name);
        tile.node->attachObject(mesh);
        mesh->begin(mat->getName(),Ogre::RenderOperation::OT_TRIANGLE_LIST,tile.group);
        tile.manual.push_back(mesh);
        return mesh;
    }
    void precipitation(Position eye,const Weather& weather,bool inside) {
        const float density=weather.dusty?.74f:weather.precipitation;
        if (inside || density<.16f) {
            if (!particles_.manual.empty()) particles_.manual.front()->setVisible(false);
            return;
        }
        auto& tile=particles_;
        Ogre::ManualObject* mesh;
        if (!tile.node) {
            tile.group="AtlasWeather";
            auto& resources=Ogre::ResourceGroupManager::getSingleton();
            resources.createResourceGroup(tile.group);
            tile.node=parent_.createChildSceneNode(tile.group);
            const auto base=Ogre::MaterialManager::getSingleton().create("AtmosphereParticles",tile.group);
            mesh=manual(tile,"particles",material(tile,base,7,false,true));
            mesh->setDynamic(true);
            mesh->setCastShadows(false);
            mesh->setRenderQueueGroup(Ogre::RENDER_QUEUE_8);
        } else {
            mesh=tile.manual.front();
            mesh->beginUpdate(0);
        }
        const bool snow=weather.temperature<-.4f && !weather.dusty;
        const bool rain=!snow && !weather.dusty;
        const float speed=rain?8.6f:snow?1.32f:.22f;
        const unsigned count=unsigned(density*(rain?170:snow?200:114));
        const auto fract=[](float x){return x-std::floor(x);};
        for (unsigned i=0;i<count;++i) {
            const float p=float(i+1);
            const float px=eye.x+17*(fract(p*.6180339f+seconds_*.053f*weather.windX)-.5f);
            const float pz=eye.z+17*(fract(p*.4683481f+seconds_*.053f*weather.windZ)-.5f);
            const float py=eye.y+8*(fract(p*.379817f-seconds_*speed/8)-.43f);
            const float width=rain?.009f:.026f+.022f*fract(p*.1367723f);
            const float height=rain?.24f:width*1.6f;
            const auto tint=rain?Ogre::ColourValue(.52f,.70f,.80f,.30f):
                snow?Ogre::ColourValue(.87f,.94f,.97f,.76f):Ogre::ColourValue(.70f,.50f,.31f,.26f);
            for (unsigned axis=0;axis<2;++axis) {
                for (const auto& [sx,sy]:std::array<Cell,4>{{{-1,0},{1,0},{1,1},{-1,1}}}) {
                    mesh->position(px+(axis==0?sx*width:0)+sy*height*.20f,
                        py+sy*height,pz+(axis==1?sx*width:0));
                    mesh->normal(0,1,0);
                    mesh->colour(tint);
                    mesh->textureCoord(float(sx),float(sy));
                }
                const auto k=i*8+axis*4;
                mesh->triangle(k,k+1,k+2);
                mesh->triangle(k,k+2,k+3);
            }
        }
        mesh->end();
        mesh->setVisible(true);
    }
    void roads(Tile& tile,Cell id,const Ogre::MaterialPtr& base) {
        const auto& spans=world_.roads(id);
        if (spans.empty()) return;
        auto* mesh=manual(tile,"roads",material(tile,base,0,false,true));
        unsigned index=0;
        for (const auto& span:spans) {
            const float dx=span.b.x-span.a.x,dz=span.b.z-span.a.z;
            const float run=std::hypot(dx,dz);
            const float nx=-dz/run*span.width*.5f,nz=dx/run*span.width*.5f;
            const unsigned divisions=std::max(1u,unsigned(std::ceil(run/2.5f)));
            const auto colour=span.bridge?Ogre::ColourValue(.19f,.12f,.074f):
                Ogre::ColourValue(.54f,.43f,.28f);
            for (unsigned i=0;i<=divisions;++i) {
                const float t=float(i)/divisions;
                for (const int side:{-1,1}) {
                    const float x=span.a.x+dx*t+nx*side,z=span.a.z+dz*t+nz*side;
                    mesh->position(x,world_.roadHeight(span,t,x,z),z);
                    mesh->normal(0,1,0);
                    mesh->textureCoord(float(side),t);
                    mesh->colour(colour);
                }
                if (i) {
                    mesh->triangle(index-2,index-1,index+1);
                    mesh->triangle(index-2,index+1,index);
                }
                index+=2;
            }
        }
        mesh->end();
    }
    template<std::size_t Rings>
    static void treeTube(Ogre::ManualObject& mesh,unsigned& index,
                         const std::array<Ogre::Vector3,Rings>& centres,
                         const std::array<float,Rings>& radii,unsigned sides,
                         float yaw) {
        const auto axis=(centres.back()-centres.front()).normalisedCopy();
        const auto u=axis.crossProduct(Ogre::Vector3(std::cos(yaw),0,std::sin(yaw))).normalisedCopy();
        const auto v=axis.crossProduct(u);
        for (unsigned ring=0;ring<Rings;++ring) {
            for (unsigned i=0;i<sides;++i) {
                const float angle=6.2831853f*i/sides;
                const auto n=u*std::cos(angle)+v*std::sin(angle);
                mesh.position(centres[ring]+radii[ring]*n);
                mesh.normal(n);
                mesh.textureCoord(float(i)/sides,float(ring)/(Rings-1));
                const float shade=.86f+.14f*std::cos(angle);
                mesh.colour(.21f*shade,.13f*shade,.073f*shade);
            }
        }
        for (unsigned ring=0;ring<Rings-1;++ring) {
            for (unsigned i=0;i<sides;++i) {
                const unsigned a=index+ring*sides+i;
                const unsigned b=index+ring*sides+(i+1)%sides;
                mesh.triangle(a,b,b+sides);
                mesh.triangle(a,b+sides,a+sides);
            }
        }
        index+=unsigned(Rings)*sides;
    }
    static void treeCrown(Ogre::ManualObject& mesh,unsigned& index,
                          const Ogre::Vector3& centre,float radius,float depth,
                          float yaw,float base,float height,bool rounded,
                          const std::array<float,8>& variance) {
        const float light=.83f+.30f*variance[7];
        const auto emit=[&](const Ogre::Vector3& position,const Ogre::Vector3& normal,
                            float shade) {
            mesh.position(position);
            mesh.normal(normal);
            mesh.textureCoord(0,std::pow(clamp((position.y-base)/height),1.6f));
            mesh.colour(.128f*shade,.285f*shade,.086f*shade);
        };
        const unsigned sides=rounded?5:6;
        const unsigned rings=rounded?2:1;
        for (unsigned ring=0;ring<rings;++ring) {
            const float width=ring==0?1.f:.72f;
            const float level=ring==0?-.23f:.24f;
            for (unsigned i=0;i<sides;++i) {
                const float angle=yaw+i*6.2831853f/sides;
                const float c=std::cos(angle),s=std::sin(angle);
                const float shape=.88f+.26f*variance[i]+.13f*std::cos(2*angle+yaw);
                const auto point=centre+Ogre::Vector3(radius*width*shape*c,
                    depth*(.11f*std::cos(2*angle+variance[6])+level),-radius*width*shape*s);
                emit(point,Ogre::Vector3(c,level,-s).normalisedCopy(),light*(.86f+.18f*ring));
            }
        }
        emit(centre+Ogre::Vector3(0,-depth*.60f,0),Ogre::Vector3::NEGATIVE_UNIT_Y,light*.66f);
        emit(centre+Ogre::Vector3(radius*.17f*std::cos(yaw),depth*(rounded?.52f:.79f),
             radius*.17f*std::sin(yaw)),Ogre::Vector3::UNIT_Y,light*1.16f);
        const unsigned cap=index+rings*sides;
        const unsigned upper=(rings-1)*sides;
        for (unsigned i=0;i<sides;++i) {
            const unsigned a=index+i,b=index+(i+1)%sides;
            mesh.triangle(cap,b,a);
            if (rounded) {
                mesh.triangle(a,b,b+upper);
                mesh.triangle(a,b+upper,a+upper);
            }
            mesh.triangle(a+upper,b+upper,cap+1);
        }
        index=cap+2;
    }
    void vegetation(Tile& tile,Cell id,const Ogre::MaterialPtr& base) {
        const auto bound=world_.corner(id);
        auto* grass=manual(tile,"meadow",material(tile,base,1,false,true));
        auto* leaves=manual(tile,"canopy",material(tile,base,2,false,true));
        auto* trunks=manual(tile,"trunks",material(tile,base,0,false,true));
        unsigned bladeIndex=0,leafIndex=0,trunkIndex=0;
        std::uint32_t pattern=world_.seed()+std::uint32_t(id.first*7477+id.second*32719+1);
        const auto draw=[&]() {
            pattern=pattern*1664525u+1013904223u;
            return float(pattern>>8)*(1.f/16777216.f);
        };
        for (int j=0;j<52;++j) {
            for (int i=0;i<52;++i) {
                const float x=bound.x+5*(i+draw()*.88f),z=bound.z-5*(j+draw()*.88f);
                if (x>=bound.x+256 || z<=bound.z-256) continue;
                const auto ground=world_.terrain().sample(x,z);
                const auto biome=ground.biome;
                if (ground.water || biome==4 || biome==5) continue;
                const auto h=[&](float a,float b){return world_.terrain().sample(a,b).height;};
                const float slope=std::hypot(h(x+2,z)-h(x-2,z),h(x,z+2)-h(x,z-2))*.25f;
                const Position p{x,ground.height,z};
                if (slope>.65f || !world_.roadClear(p)) continue;
                const float wave=.5f+.26f*std::sin(x*.13f+z*.03f)+.22f*std::sin(z*.16f-x*.06f);
                const float yaw=draw()*6.2831853f;
                if (draw()<.32f+.60f*wave) {
                    for (unsigned k=0;k<3;++k) {
                        const float angle=yaw+k*2.0943951f;
                        const float a=std::cos(angle),b=std::sin(angle);
                        const float size=.24f+.50f*wave*draw();
                        const auto emit=[&](float px,float py,float pz,float flex) {
                            grass->position(px,py,pz);
                            grass->normal(0,1,0);
                            grass->textureCoord(0,flex);
                            grass->colour(.15f+flex*.16f,.26f+flex*.20f,.073f+flex*.066f);
                        };
                        emit(x+a*.042f,p.y-.05f,z+b*.042f,0);
                        emit(x-a*.042f,p.y-.05f,z-b*.042f,0);
                        emit(x+b*.21f,p.y+size,z-a*.21f,1);
                        grass->triangle(bladeIndex,bladeIndex+1,bladeIndex+2);
                        bladeIndex+=3;
                    }
                }
                const float woodland=biome==1?.042f:biome==6?.016f:.008f;
                if (draw()>woodland || !world_.roadClear(p,2.5f)) continue;
                const float height=3.4f+4.3f*draw();
                // Keep the 48 foliage draws per tree so existing seeds keep
                // the same tree placement and grass distribution.
                std::array<std::array<float,8>,6> foliage{};
                for (auto& cluster:foliage) {
                    for (float& value:cluster) value=draw();
                }
                const auto& tree=foliage.back();
                const float broadleafChance=biome==1?.46f:biome==3?.12f:biome==6?.86f:.72f;
                const bool broadleaf=tree[0]<broadleafChance;
                const float radius=height*(broadleaf?.050f:.038f);
                tile.trunks.emplace_back(x,p.y,z,radius);
                const float lean=.026f+.065f*tree[1];
                const auto stem=[&](float level) {
                    const float sway=height*level*level*lean;
                    return Ogre::Vector3(x+sway*std::cos(yaw),p.y+height*level,
                                         z+sway*std::sin(yaw));
                };
                treeTube(*trunks,trunkIndex,std::array{stem(-.04f),stem(.12f),stem(.83f)},
                         std::array{radius*1.10f,radius*.77f,radius*.22f},6,yaw);
                const float spread=.83f+.26f*tree[2];
                for (unsigned limb=0;limb<4;++limb) {
                    const float angle=yaw+limb*2.39996f;
                    const float jitter=(tree[limb+3]-.50f)*.042f;
                    const float level=(broadleaf?.61f+limb*.048f:.37f+limb*.104f)+jitter;
                    const float reach=(broadleaf?.235f-limb*.015f:.274f-limb*.053f)*height*spread;
                    const auto tip=stem(level)+Ogre::Vector3(std::cos(angle)*reach,0,std::sin(angle)*reach);
                    if (limb<2) {
                        const auto start=stem(level-(broadleaf?.20f:.08f));
                        treeTube(*trunks,trunkIndex,std::array{start,tip},
                                 std::array{radius*.45f,radius*.09f},4,angle+1.5707963f);
                    }
                    const float width=(broadleaf?.205f:.165f-limb*.015f)*height*spread;
                    treeCrown(*leaves,leafIndex,tip,width,height*(broadleaf?.27f:.26f),
                              angle,p.y,height,broadleaf,foliage[limb]);
                }
                treeCrown(*leaves,leafIndex,stem(.87f),height*(broadleaf?.19f:.13f)*spread,
                          height*(.23f+.06f*tree[7]),yaw,p.y,height,broadleaf,foliage[4]);
            }
        }
        for (auto* mesh:{grass,leaves,trunks}) mesh->end();
        grass->setCastShadows(false);
        leaves->setCastShadows(false);
        tile.effects.emplace_back(grass,1,"-");
        tile.effects.emplace_back(leaves,2,"-");
    }
    void terrain(Tile& tile,Cell c) {
        auto& mgr=Ogre::MaterialManager::getSingleton();
        const auto base=mgr.create(tile.group+"_GroundTemplate",tile.group);
        const auto bound=world_.corner(c);
        auto* map=manual(tile,"ground",material(tile,base,0,false,true));
        constexpr int n=17;
        const std::array<Ogre::ColourValue,8> palette{
            Ogre::ColourValue(.28,.37,.19),Ogre::ColourValue(.12,.27,.12),
            Ogre::ColourValue(.24,.38,.12),Ogre::ColourValue(.29,.32,.25),
            Ogre::ColourValue(.69,.78,.79),Ogre::ColourValue(.55,.38,.21),
            Ogre::ColourValue(.17,.28,.13),Ogre::ColourValue(.37,.41,.18)};
        std::array<Ground,n*n> samples{};
        for (int j=0;j<n;++j) {
            for (int i=0;i<n;++i) {
                const float x=bound.x+i*16, z=bound.z-j*16;
                const auto point=world_.terrain().sample(x,z);
                const float dx=world_.terrain().sample(x+8,z).height-world_.terrain().sample(x-8,z).height;
                const float dz=world_.terrain().sample(x,z+8).height-world_.terrain().sample(x,z-8).height;
                map->position(x,point.height,z);
                map->normal(Ogre::Vector3(-dx,16,-dz).normalisedCopy());
                map->textureCoord(x*.5f,z*.5f);
                map->colour(palette[point.biome]);
                samples[j*n+i]=point;
            }
        }
        for (unsigned j=0;j<n-1;++j) {
            for (unsigned i=0;i<n-1;++i) {
                const auto k=j*n+i;
                map->triangle(k,k+1,k+n+1);
                map->triangle(k,k+n+1,k+n);
            }
        }
        map->end();
        roads(tile,c,base);
        vegetation(tile,c,base);
        for (const bool seasonal:{false,true}) {
            auto* water=manual(tile,seasonal?"wet_season":"water",
                               material(tile,base,4,false,true));
            unsigned count=0;
            for (int j=0;j<n-1;++j) {
                for (int i=0;i<n-1;++i) {
                    const auto k=j*n+i;
                    const auto legal=[&](unsigned v) {
                        return v!=0 && (v==3)==seasonal;
                    };
                    if (!legal(samples[k].water) || !legal(samples[k+1].water) ||
                        !legal(samples[k+n].water) || !legal(samples[k+n+1].water)) continue;
                    for (const auto& [a,b]:std::array<Cell,4>{{{0,0},{1,0},{1,1},{0,1}}}) {
                        water->position(bound.x+(i+a)*16,samples[k+a+b*n].level+.015f,
                                        bound.z-(j+b)*16);
                        water->normal(0,1,0);
                        water->textureCoord(float(a),float(b));
                        water->colour(.20f,.47f,.54f,1);
                    }
                    water->triangle(count,count+1,count+2);
                    water->triangle(count,count+2,count+3);
                    count+=4;
                }
            }
            water->end();
            water->setCastShadows(false);
            tile.effects.emplace_back(water,4,seasonal?"SEASONAL":"-");
        }
    }
    void fountains(Tile& tile) {
        auto& mgr=Ogre::MaterialManager::getSingleton();
        const auto source=mgr.create(tile.group+"_FountainTemplate",tile.group);
        for (const auto& item:tile.actions) {
            if (item.kind!="FOUNTAIN_WATER" && item.kind!="WELL_WATER") continue;
            auto* mesh=manual(tile,item.id,material(tile,source,6,false,true));
            const auto p=item.position;
            const auto emit=[&](float x,float y,float z) {
                mesh->position(x,y,z);
                mesh->normal(0,1,0);
                mesh->textureCoord(x*.25f,z*.25f);
                mesh->colour(.24f,.52f,.58f,1);
            };
            emit(p.x,p.y,p.z);
            for (unsigned i=0;i<20;++i) {
                const float a=i*.31415926f;
                emit(p.x+std::cos(a)*item.size.x*.5f,p.y,p.z+std::sin(a)*item.size.z*.5f);
                mesh->triangle(0,1+(i+1)%20,1+i);
            }
            if (item.kind=="FOUNTAIN_WATER") {
                unsigned offset=21;
                for (unsigned jet=0;jet<6;++jet) {
                    const float angle=jet*1.0472f;
                    const float gx=std::cos(angle),gz=std::sin(angle);
                    for (unsigned i=0;i<8;++i) {
                        const float u=i/7.f;
                        const float x=p.x+gx*(.26f+u*item.size.x*.35f);
                        const float z=p.z+gz*(.26f+u*item.size.z*.35f);
                        const float y=p.y+.68f-.68f*u+.75f*4*u*(1-u);
                        emit(x+gz*.024f,y,z-gx*.024f);
                        emit(x-gz*.024f,y,z+gx*.024f);
                        if (i) {
                            const auto k=offset+(i-1)*2;
                            mesh->triangle(k,k+1,k+3);
                            mesh->triangle(k,k+3,k+2);
                        }
                    }
                    offset+=16;
                }
            }
            mesh->end();
            mesh->setCastShadows(false);
            tile.effects.emplace_back(mesh,6,"-");
        }
    }
    void load(Cell id) {
        auto& tile=tiles_.try_emplace(id).first->second;
        const auto label=std::to_string(id.first)+"_"+std::to_string(id.second);
        const auto directory=world_.root()/"tiles"/label;
        tile.group="Atlas_"+label;
        auto& resources=Ogre::ResourceGroupManager::getSingleton();
        resources.createResourceGroup(tile.group);
        tile.node=parent_.createChildSceneNode(tile.group);
        try {
            if (std::filesystem::is_regular_file(directory/".atlas_bake")) {
                resources.addResourceLocation(directory.string(),"FileSystem",tile.group,true);
                resources.initialiseResourceGroup(tile.group);
                attach(tile,directory,"settlement.tsv",false);
                attach(tile,directory,"effects.tsv",true);
                tile.actions=loadInteractions(directory);
                std::copy_if(tile.actions.begin(),tile.actions.end(),std::back_inserter(tile.lamps),
                    [](const auto& item){return item.kind=="STREET_LIGHT" || item.kind=="DUNGEON_LAMP";});
                fountains(tile);
                tile.collider=std::make_unique<Collider>(
                    ProceduralAssets::loadCollision(directory/"static.collision.bin"));
            } else {
                terrain(tile,id);
            }
        } catch (...) {
            unload(tiles_.find(id));
            throw;
        }
    }
    void release(Tile& tile) {
        for (auto* object:tile.entities) scene_.destroyEntity(object);
        for (auto* object:tile.manual) scene_.destroyManualObject(object);
        tile.node->removeAndDestroyAllChildren();
        scene_.destroySceneNode(tile.node);
        tile.materials.clear();
        Ogre::ResourceGroupManager::getSingleton().destroyResourceGroup(tile.group);
    }
    void unload(std::map<Cell,Tile>::iterator it) {
        release(it->second);
        tiles_.erase(it);
    }
};

}  // namespace MedievalAtlas
