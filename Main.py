import json, time, os, questionary
import pandas as pd

from typing import Dict, Tuple, List, Literal, Union
from concurrent.futures import (
    ThreadPoolExecutor,
    Future,
    as_completed,
)
from tqdm import tqdm, trange


from Helper.File import ChoseFilesToOpen
from Helper.ProcessDeviceName import CPUName, GPUName
from Helper.Get3DMarkScore import GetNameFromId, GetMedianScoreFromId, TESTSCENE


DATA_TYPE = Dict[int, Dict[str, Union[int, str]]]


def GetAllDeviceInfo(IsCpu: bool, *Args: int) -> DATA_TYPE:
    IdToDeviceInfo: DATA_TYPE
    DEVICE: str = "CPU" if IsCpu else "GPU"
    MinId: int = 1
    MaxId: int = 4000 if IsCpu else 2000
    if len(Args) > 0:
        MinId = Args[0]
    if len(Args) > 1:
        MaxId = Args[1]

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as ThreadPool:
        # 从id获取型号
        print("------------------------------------------")
        print(f"Get {DEVICE} Name From ID ({MinId} To {MaxId})")
        Threads: List[Future] = []
        Threads.extend(
            ThreadPool.submit(GetNameFromId, i, IsCpu)
            for i in trange(MinId, MaxId + 1, desc="Tasks Submitting...", unit="tasks")
        )

        IdToDeviceInfo = {}
        with tqdm(
            as_completed(Threads),
            total=MaxId - MinId + 1,
            desc="Tasks Executing...",
            unit="tasks",
        ) as ProgressBar:
            for Thread in ProgressBar:
                try:
                    Result: Tuple[int, str] = Thread.result()
                    if Result[1] != "":
                        Item = {
                            f"{DEVICE} ID": Result[0],
                            f"{DEVICE} Name": Result[1],
                        }
                        if IsCpu:
                            Item[TESTSCENE.CPU_SINGLECORE.value[2]] = -1
                            Item[TESTSCENE.CPU_ALLCORES.value[2]] = -1
                        else:
                            Item[TESTSCENE.GPU_GRAPHICS.value[2]] = -1
                            Item[TESTSCENE.GPU_RAYTRACING.value[2]] = -1
                        IdToDeviceInfo[Result[0]] = Item

                        ProgressBar.set_description_str(
                            f"Tasks Executing... Current {DEVICE}:{Result[1]:^35}"
                        )
                except Exception as e:
                    print(f"====== An Exception Raised! ======\n{e}")

        def GetScore(
            TestScene: Literal[
                TESTSCENE.CPU_SINGLECORE,
                TESTSCENE.CPU_ALLCORES,
                TESTSCENE.GPU_GRAPHICS,
                TESTSCENE.GPU_RAYTRACING,
            ]
        ) -> None:
            Threads.clear()
            Threads.extend(
                ThreadPool.submit(GetMedianScoreFromId, TestScene, i)
                for i in tqdm(
                    IdToDeviceInfo.keys(), desc="Tasks Submitting...", unit="tasks"
                )
            )

            with tqdm(
                as_completed(Threads),
                total=len(Threads),
                desc="Tasks Executing...",
                unit="tasks",
            ) as ProgressBar:
                for Thread in ProgressBar:
                    try:
                        Result: Tuple[int, int] = Thread.result()
                        IdToDeviceInfo[Result[0]][TestScene.value[2]] = Result[1]

                        CurrentDeviceName = IdToDeviceInfo[Result[0]][f"{DEVICE} Name"]
                        ProgressBar.set_description_str(
                            f"Tasks Executing... Current {DEVICE}:{CurrentDeviceName:^35}"
                        )
                    except Exception as e:
                        print(f"====== An Exception Raised! ======\n{e}")

        # 从id获取分数
        TestSceneList = (
            [TESTSCENE.CPU_SINGLECORE, TESTSCENE.CPU_ALLCORES]
            if IsCpu
            else [TESTSCENE.GPU_GRAPHICS, TESTSCENE.GPU_RAYTRACING]
        )
        for TestScene in TestSceneList:
            print("------------------------------------------")
            print(f"Get {TestScene.value[2]}")
            GetScore(TestScene)

    return IdToDeviceInfo


def ProcessData(Data: DATA_TYPE, IsCpu: bool) -> None:
    if len(Data) == 0:
        return

    # 将dict转为dataframe，导出excel
    COL_NAME = "CPU Name" if IsCpu else "GPU Name"
    COL_NAME_GUID = f"{COL_NAME} GUID"
    COL_ID = "CPU ID" if IsCpu else "GPU ID"
    COL_SCORE = (
        TESTSCENE.CPU_SINGLECORE.value[2] if IsCpu else TESTSCENE.GPU_GRAPHICS.value[2]
    )
    COL_VENDOR = "Vendor"
    COL_MODEL = "Model"
    SCORE_LIMIT = 0
    GUID_CLASS = CPUName if IsCpu else GPUName

    Df = pd.DataFrame(Data.values())
    # 剔除名字为空
    Df = Df[Df[COL_NAME] != ""]
    # 数据转为int
    Df[COL_ID] = Df[COL_ID].astype(int)
    Df[COL_SCORE] = Df[COL_SCORE].astype(int)
    # 剔除分数过低数据
    Df = Df[Df[COL_SCORE] >= SCORE_LIMIT]
    # 根据Name生成GUID
    Df[COL_NAME_GUID] = Df[COL_NAME].apply(GUID_CLASS)
    # 新增 Vendor，Model 列
    VendorSeries = Df[COL_NAME_GUID].apply(lambda Obj: Obj.Vendor)
    Df.insert(Df.columns.get_loc(COL_NAME), COL_VENDOR, VendorSeries)
    ModelSeries = Df[COL_NAME_GUID].apply(lambda Obj: Obj.Model)
    Df.insert(Df.columns.get_loc(COL_NAME), COL_MODEL, ModelSeries)
    # 根据 Score 排序
    Df.sort_values(COL_SCORE, ascending=False, inplace=True)
    Df.reset_index(drop=True, inplace=True)

    # 直接保存到根目录下
    root_dir = os.path.dirname(os.path.abspath(__file__))
    filename = "CPU_Result.xlsx" if IsCpu else "GPU_Result.xlsx"
    save_path = os.path.join(root_dir, filename)
    with pd.ExcelWriter(save_path, engine="openpyxl") as w:
        Df.to_excel(w, sheet_name="Sheet1", index=False)

    print(f"结果已保存至: {save_path}")
    print(Df)


def Main() -> None:
    MODES_TO_CHOOSE = ["1) Full Update.", "2) Process Local Data."]
    Mode = questionary.select(
        message="选择模式：\n"
        + "1) 全量更新，从3dmark爬取数据，保存到本地（json格式），然后处理数据导出Excel\n"
        + "2) 从本地的json文件中读取数据，处理数据导出Excel\n"
        + "Choose mode:\n"
        + "1) Full update, scrape data from 3DMark, save to local (json format), then process data and export to Excel.\n"
        + "2) Read data from local json files, process data and export to Excel.\n",
        choices=MODES_TO_CHOOSE,
        show_selected=True,
    ).ask()

    IsCpu: bool
    Data: DATA_TYPE
    if Mode == MODES_TO_CHOOSE[0]:
        Device = questionary.select(
            message="要爬哪个数据？\n"
            + "Which score to scrape?\n"
            + "1) CPU, 3DMark CPU Profile Single Core & All Cores\n"
            + "2) GPU, 3DMark Time Spy & Port Royal\n",
            choices=["1) CPU", "2) GPU"],
            show_selected=True,
        ).ask()
        IsCpu = "CPU" in Device

        StartTime = time.time()
        Data = GetAllDeviceInfo(IsCpu)
        print(f"\nTotal time:{time.time() - StartTime:.2f}s")

        # 直接保存到根目录下
        root_dir = os.path.dirname(os.path.abspath(__file__))
        filename = "CPU_Result.json" if IsCpu else "GPU_Result.json"
        save_path = os.path.join(root_dir, filename)
        with open(save_path, "w", encoding="utf-8") as File:
            json.dump(Data, File)
        print(f"原始数据已保存至: {save_path}")

    elif Mode == MODES_TO_CHOOSE[1]:
        # 将多个文件读入
        DataList: List[DATA_TYPE] = []
        Files: Tuple[str] = ChoseFilesToOpen(
            FileTypes=[("Json File", ".json")], bForce=False
        )
        if not Files:
            return
        for FilePath in Files:
            with open(FilePath, "r", encoding="utf-8") as File:
                DataList.append(json.load(File))

        # 将数据合并到一个dict中
        Data = dict()
        for TempData in DataList:
            Data.update(TempData)

        Value = next(iter(Data.values()))
        IsCpu = "CPU Name" in Value

    else:
        print("输入错误！\nInvalid input!\n")
        return

    ProcessData(Data, IsCpu)


if __name__ == "__main__":
    Main()

