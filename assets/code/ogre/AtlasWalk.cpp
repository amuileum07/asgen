#include "AtlasRenderer.hpp"
#include <OgreWindowEventUtilities.h>
#include <chrono>
#include <iostream>
#include <thread>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {
bool key(int value) {
#ifdef _WIN32
    return (GetAsyncKeyState(value) & 0x8000)!=0;
#else
    (void)value;
    return false;
#endif
}
}

int main(int argc,char** argv) try {
    using namespace MedievalAtlas;
    if (argc<4 || argc>6)
        throw std::runtime_error(
            "Run AtlasWalk <atlas folder> <GL3Plus plugin> <site or dungeon> [frames] [screen.png]");
    const int frames=argc>4?std::stoi(argv[4]):0;
    expect(frames>=0,"Frame count must be nonnegative");
    World state(argv[1]);
    Position foot{};
    if (const auto city=state.destinations().find(argv[3]);city!=state.destinations().end()) {
        foot=city->second;
        foot.y+=.15f;
    } else {
        foot=state.dungeons().at(argv[3]).entrance;
        foot.z-=1.1f;
    }
    const auto saveTo=state.root()/"walk.save.tsv";
    if (!frames) {
        std::ifstream input(saveTo);
        if (input) state.restore(input);
    }
    Ogre::Root root("","",(state.root()/"AtlasWalk.log").string());
    root.loadPlugin(argv[2]);
    const auto& available=root.getAvailableRenderers();
    expect(!available.empty(),"No OGRE render system");
    root.setRenderSystem(available.front());
    root.initialise(false);
    Ogre::NameValuePairList hints{{"gamma","true"},{"vsync","true"}};
    if (frames) hints["hidden"]="true";
    auto* window=root.createRenderWindow("Procedural Atlas",1280,720,false,&hints);
    auto* manager=root.createSceneManager();
    Ogre::ResourceGroupManager::getSingleton().initialiseAllResourceGroups();
    auto* parent=manager->getRootSceneNode()->createChildSceneNode("World");
    auto* camera=manager->createCamera("Player");
    camera->setNearClipDistance(.065f);
    camera->setFarClipDistance(1550);
    camera->setAutoAspectRatio(true);
    auto* neck=manager->getRootSceneNode()->createChildSceneNode("Head");
    neck->attachObject(camera);
    auto* viewport=window->addViewport(camera);
    Renderer scene(state,*manager,*parent);
    float yaw=0,pitch=.045f;
    bool interact=false;
    using Clock=std::chrono::steady_clock;
    auto then=Clock::now();
    std::vector<double> times;
    for (int frame=0;!window->isClosed() && !key(27) && (!frames || frame<frames);++frame) {
#if OGRE_VERSION_MAJOR >= 14
        OgreBites::WindowEventUtilities::messagePump();
#else
        Ogre::WindowEventUtilities::messagePump();
#endif
        const auto start=Clock::now();
        const float dt=std::clamp(std::chrono::duration<float>(start-then).count(),.005f,.05f);
        then=start;
        const auto forward=Ogre::Vector3(std::sin(yaw),0,-std::cos(yaw));
        const auto right=Ogre::Vector3(std::cos(yaw),0,std::sin(yaw));
        yaw+=((key(39)?1:0)-(key(37)?1:0))*dt*1.6f;
        pitch=clamp(pitch+((key(40)?1:0)-(key(38)?1:0))*dt,-1.15f,1.15f);
        const auto direction=forward*((key('W')?1:0)-(key('S')?1:0))+
                             right*((key('D')?1:0)-(key('A')?1:0));
        if (direction.squaredLength()>0) {
            const auto step=direction.normalisedCopy()*(1.45f*dt*state.surface(foot).traction);
            if (auto next=scene.tryStep(foot,step.x,step.z)) foot=*next;
        }
        const Position eye{foot.x,foot.y+1.70f,foot.z};
        neck->setPosition(eye.x,eye.y,eye.z);
        neck->setDirection(Ogre::Vector3(forward.x,-std::tan(pitch),forward.z),
                           Ogre::Node::TS_WORLD,Ogre::Vector3::NEGATIVE_UNIT_Z);
        const bool inside=foot.y<state.terrain().sample(foot.x,foot.z).height-1.0f;
        const auto w=state.sky(eye,inside);
        viewport->setBackgroundColour(Ogre::ColourValue(
            .47f*w.daylight,.68f*w.daylight,.80f*w.daylight));
        scene.update(eye,dt,inside);
        if (key('E') && !interact) {
            if (auto target=scene.nearby(eye)) {
                state.activateClue(*target);
                const bool reward=state.claim(*target);
                state.recordChange(target->id+"_visited");
                std::cout<<target->kind<<" "<<target->id<<(reward?" collected":"")<<'\n';
            }
        }
        interact=key('E');
        if (!root.renderOneFrame()) break;
        if (frames && frame>1)
            times.push_back(std::chrono::duration<double,std::milli>(Clock::now()-start).count());
    }
    if (argc==6) window->writeContentsToFile(argv[5]);
    if (!frames) {
        std::ofstream output(saveTo);
        state.save(output);
    }
    if (!times.empty()) {
        std::sort(times.begin(),times.end());
        std::cout<<"ATLAS_RENDER_OK frame p95 "<<times[std::size_t((times.size()-1)*.95)]
                 <<" ms\n";
    }
} catch (const std::exception& error) {
    std::cerr<<error.what()<<'\n';
    return 1;
}
