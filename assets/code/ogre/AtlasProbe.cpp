#include "AtlasRuntime.hpp"
#include <iostream>

int main(int argc, char** argv) try {
    using namespace MedievalAtlas;
    if (argc!=2) throw std::runtime_error("Run AtlasProbe <atlas folder>");
    World world(argv[1]);
    expect(!world.destinations().empty(),"Atlas has no settlements");
    const auto& hubEntry = *world.destinations().begin();
    const auto& hubId = hubEntry.first;
    const auto& hub = hubEntry.second;
    float lowest=0, highest=0;
    for (const auto& [id,point]:world.destinations()) {
        (void)point;
        for (const auto hour:{8.,2175.,4355.,6481.}) {
            world.setHours(hour);
            expect(!world.route(hubId,id).empty(),"Disconnected town");
        }
    }
    std::string sampleDungeon;
    for (const auto& [id,dungeon]:world.dungeons()) {
        if (sampleDungeon.empty()) sampleDungeon = id;
        expect(world.triggerSeal(id).has_value(),"Missing active dungeon seal");
        world.activateClue({"test_clue","SEAL_CLUE",dungeon.seal,dungeon.entrance,{}});
        expect(!world.triggerSeal(id),"Clue did not open seal");
        const Interaction relic{id+"_reward","SEALED_RELIC",dungeon.seal,dungeon.entrance,{}};
        expect(world.claim(relic) && !world.claim(relic),"Reward is not idempotent");
    }
    for (unsigned hour=0;hour<8640;hour+=37) {
        world.setHours(hour);
        const auto weather=world.sky(hub);
        lowest=std::min(lowest,weather.temperature);
        highest=std::max(highest,weather.temperature);
        expect(weather.fog>=0 && weather.fog<=1 && weather.wetness>=0 &&
               weather.wetness<=1,"Invalid climate limits");
        const auto cells=world.visibleTiles(hub);
        expect(cells.size()==25 && cells.at(world.cell(hub.x,hub.z))==0,
               "Invalid streaming window");
    }
    expect(highest-lowest>9,"Missing seasonal climate variation");
    world.press(hub);
    expect(world.presses().size()==1,"Missing grass press");
    world.advance(3.f);
    expect(world.presses().empty(),"Grass failed to recover");
    world.recordChange("probe_world_change");
    std::stringstream serial;
    world.save(serial);
    World restored(argv[1]);
    restored.restore(serial);
    expect(restored.hours()==world.hours() &&
           restored.changed("probe_world_change") &&
           (sampleDungeon.empty() || restored.collected(sampleDungeon+"_reward")),
           "Atlas save did not round-trip");
    std::cout<<"ATLAS_RUNTIME_OK "<<world.destinations().size()<<" towns, "
             <<world.dungeons().size()<<" dungeons\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr<<error.what()<<'\n';
    return 1;
}
