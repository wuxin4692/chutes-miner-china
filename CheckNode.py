import json
import urllib.request
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import math

class ChuteStatsVisualizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Chute 部署统计工具")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        # 设置中文字体支持
        self.font_config = ('SimHei', 10)
        self.title_font = ('SimHei', 12, 'bold')
        
        # 创建输入区域
        input_frame = ttk.LabelFrame(root, text="输入标识符", padding="10")
        input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(input_frame, text="标识符:", font=self.font_config).pack(side=tk.LEFT, padx=5)
        self.id_entry = ttk.Entry(input_frame, width=50, font=self.font_config)
        self.id_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.id_entry.insert(0, "5G1RmD7DKHSwzHJuwMcCgHsY3ZFXDze1LDThavUnMV2rNGSk")
        
        ttk.Button(input_frame, text="获取统计", command=self.fetch_and_display_stats).pack(side=tk.LEFT, padx=5)
        
        # 创建统计结果区域
        stats_frame = ttk.LabelFrame(root, text="统计结果", padding="10")
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 创建选项卡
        self.tab_control = ttk.Notebook(stats_frame)
        self.tab_control.pack(fill=tk.BOTH, expand=True)
        
        # 文本统计选项卡
        self.text_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.text_tab, text="文本统计")
        
        self.stats_text = scrolledtext.ScrolledText(self.text_tab, wrap=tk.WORD, font=self.font_config)
        self.stats_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 图表统计选项卡
        self.chart_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.chart_tab, text="图表统计")
        
        # 创建Canvas用于绘制图表
        self.canvas = tk.Canvas(self.chart_tab, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 状态栏
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, font=self.font_config)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def fetch_data(self, identifier):
        """从URL获取JSON数据"""
        try:
            self.status_var.set("正在获取数据...")
            self.root.update()
            
            # 这里假设API URL格式，实际使用时请替换为正确的API端点
            url = f"https://api.chutes.ai/nodes/?detailed=true&hotkey={identifier}"  # 请替换为实际API地址
            
            # 如果你有实际的API地址，可以取消下面的注释，并注释掉模拟数据部分
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())
            
            # 模拟数据 - 实际使用时请删除这部分，使用上面的API调用
            # mock_data = '''
            # {"5G1RmD7DKHSwzHJuwMcCgHsY3ZFXDze1LDThavUnMV2rNGSk":{
            #   "provisioned":[
            #     {"gpu":"4090","chute":{"username":"chutes","name":"cognitivecomputations/Dolphin3.0-Mistral-24B","chute_id":"ad6495fd-9869-5367-8492-c073d28026da","verified":true,"instance_id":"470e9a78-ede5-4188-9021-648d63600aa0"}},
            #     {"gpu":"4090","chute":{"username":"chutes","name":"BAAI/bge-large-en-v1.5","chute_id":"487d508a-0771-5f19-9cde-c69ad8948ff1","verified":true,"instance_id":"2d098e40-e5f9-4555-9adf-c7ba0c255428"}},
            #     {"gpu":"4090","chute":{"username":"chutes","name":"cognitivecomputations/Dolphin3.0-Mistral-24B","chute_id":"ad6495fd-9869-5367-8492-c073d28026da","verified":true,"instance_id":"470e9a78-ede5-4188-9021-648d63600aa0"}},
            #     {"gpu":"4090","chute":{"username":"chutes","name":"BAAI/bge-large-en-v1.5","chute_id":"487d508a-0771-5f19-9cde-c69ad8948ff1","verified":true,"instance_id":"492cfa40-20d4-40b7-9ab5-648f74401dc8"}},
            #     {"gpu":"4090","chute":{"username":"kikakkz","name":"cosy-voice-tts","chute_id":"9f0b1a2a-8b4f-5c57-a18a-7525d50e5df7","verified":true,"instance_id":"b3d7c8c6-0137-4363-932a-2a58b8b9f148"}},
            #     {"gpu":"4090","chute":{"username":"chutes","name":"cognitivecomputations/Dolphin3.0-Mistral-24B","chute_id":"ad6495fd-9869-5367-8492-c073d28026da","verified":true,"instance_id":"470e9a78-ede5-4188-9021-648d63600aa0"}},
            #     {"gpu":"4090","chute":{"username":"chutes","name":"cognitivecomputations/Dolphin3.0-Mistral-24B","chute_id":"ad6495fd-9869-5367-8492-c073d28026da","verified":true,"instance_id":"470e9a78-ede5-4188-9021-648d63600aa0"}},
            #     {"gpu":"4090","chute":{"username":"chutes","name":"BAAI/bge-large-en-v1.5","chute_id":"487d508a-0771-5f19-9cde-c69ad8948ff1","verified":true,"instance_id":"160f9fb8-477a-40d4-a99a-22e094ab8741"}},
            #     {"gpu":"4090","chute":{"username":"affine2","name":"Alphatao/Affine-2333827","chute_id":"c1c99f98-1613-598f-86d1-93e22fdb34ca","verified":true,"instance_id":"f9656c09-fd2f-41e3-81be-e0037cd741ee"}}
            #   ],
            #   "idle":{"4090":1}
            # }}
            # '''
            #data = json.loads(mock_data)
            
            self.status_var.set("数据获取成功")
            return data
        except Exception as e:
            self.status_var.set(f"获取数据失败: {str(e)}")
            messagebox.showerror("错误", f"无法获取数据: {str(e)}")
            return None
    
    def analyze_data(self, data):
        """分析数据并返回统计结果"""
        if not data:
            return None
            
        try:
            # 提取内层数据（外层键是输入的标识符）
            identifier = next(iter(data.keys()))
            inner_data = data[identifier]
            provisioned = inner_data["provisioned"]  # 已部署的 Chute 列表
            idle_gpus = inner_data["idle"]  # 空闲 GPU 信息
            
            # 初始化统计变量
            total_provisioned = len(provisioned)  # 已部署 Chute 总数
            gpu_count = defaultdict(int)  # 各 GPU 型号的部署数量
            chute_name_count = defaultdict(int)  # 各 Chute 名称的部署频次
            verified_count = 0  # 验证通过的 Chute 数量
            
            # 遍历已部署 Chute 列表，统计数据
            for item in provisioned:
                # 统计 GPU 型号
                gpu = item["gpu"]
                gpu_count[gpu] += 1
                
                # 统计 Chute 名称
                chute_name = item["chute"]["name"]
                chute_name_count[chute_name] += 1
                
                # 统计验证状态
                if item["chute"]["verified"]:
                    verified_count += 1
            
            return {
                "total_provisioned": total_provisioned,
                "verified_count": verified_count,
                "gpu_count": dict(gpu_count),
                "chute_name_count": dict(chute_name_count),
                "idle_gpus": idle_gpus
            }
        except Exception as e:
            messagebox.showerror("错误", f"数据分析失败: {str(e)}")
            return None
    
    def display_text_stats(self, stats):
        """在文本选项卡中显示统计结果"""
        if not stats:
            return
            
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, "===== Chute 部署统计结果 =====\n\n")
        self.stats_text.insert(tk.END, f"1. 已部署 GPU 总数: {stats['total_provisioned']}\n")
        self.stats_text.insert(tk.END, f"2. 验证通过的 GPU: {stats['verified_count']} "
                                 f"(占比: {stats['verified_count']/stats['total_provisioned']:.2%})\n\n")
        
        self.stats_text.insert(tk.END, "3. GPU 型号部署分布:\n")
        for gpu, count in stats['gpu_count'].items():
            self.stats_text.insert(tk.END, f"   - {gpu}: {count} 张 "
                                     f"(占比: {count/stats['total_provisioned']:.2%})\n")
        
        self.stats_text.insert(tk.END, "\n4. 模型使用的显卡:\n")
        for name, count in sorted(stats['chute_name_count'].items(), key=lambda x: x[1], reverse=True):
            self.stats_text.insert(tk.END, f"   - {name}: {count} 次\n")
        
        self.stats_text.insert(tk.END, "\n5. 空闲 GPU 数量:\n")
        for gpu, count in stats['idle_gpus'].items():
            self.stats_text.insert(tk.END, f"   - {gpu}: {count} 个空闲\n")
        
        self.stats_text.insert(tk.END, "\n==============================\n")
    
    def draw_charts(self, stats):
        """在图表选项卡中绘制统计图表"""
        if not stats:
            return
            
        # 清除画布
        self.canvas.delete("all")
        
        # 获取画布尺寸
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        # 如果窗口还没渲染完成，使用默认尺寸
        if width < 100:
            width = 800
        if height < 100:
            height = 500
        
        # 绘制标题
        self.canvas.create_text(width/2, 20, text="Chute 部署统计图表", font=self.title_font)
        
        # 绘制两个图表：GPU分布和Chute名称分布
        # 1. GPU部署分布图(上半部分)
        self.draw_bar_chart(
            stats['gpu_count'], 
            "GPU型号部署分布",
            50, 50, width-100, height//2 - 80,
            ["#4CAF50", "#2196F3", "#FF9800", "#f44336", "#9C27B0"]
        )
        
        # 2. Chute名称部署频次图(下半部分)
        self.draw_bar_chart(
            stats['chute_name_count'], 
            "Chute名称部署频次",
            50, height//2, width-100, height//2 - 80,
            ["#e91e63", "#3f51b5", "#009688", "#673ab7", "#ff5722"]
        )
    
    def draw_bar_chart(self, data, title, x, y, width, height, colors):
        """绘制条形图"""
        if not data or len(data) == 0:
            self.canvas.create_text(x + width/2, y + height/2, text="无数据可显示", font=self.font_config)
            return
            
        # 绘制标题
        self.canvas.create_text(x + width/2, y, text=title, font=self.title_font)
        
        # 准备数据
        items = sorted(data.items(), key=lambda x: x[1], reverse=True)
        labels = [item[0] for item in items]
        values = [item[1] for item in items]
        max_value = max(values) if values else 1
        
        # 计算条形图参数
        bar_count = len(items)
        bar_width = min(50, width / bar_count * 0.6)
        spacing = width / bar_count
        
        # 绘制坐标轴
        axis_bottom = y + height - 30
        self.canvas.create_line(x, axis_bottom, x + width, axis_bottom, width=2)  # X轴
        self.canvas.create_line(x, y + 30, x, axis_bottom, width=2)  # Y轴
        
        # 绘制条形和标签
        for i, (label, value) in enumerate(zip(labels, values)):
            # 计算条形高度和位置
            bar_height = (value / max_value) * (height - 60)
            bar_x = x + spacing * i + (spacing - bar_width) / 2
            bar_y = axis_bottom - bar_height
            
            # 绘制条形
            color = colors[i % len(colors)]
            self.canvas.create_rectangle(bar_x, bar_y, bar_x + bar_width, axis_bottom, fill=color)
            
            # 绘制数值标签
            self.canvas.create_text(bar_x + bar_width/2, bar_y - 15, text=str(value), font=self.font_config)
            
            # 绘制X轴标签（旋转45度以便显示长文本）
            label_x = bar_x + bar_width/2
            label_y = axis_bottom + 25
            self.canvas.create_text(label_x, label_y, text=label, font=self.font_config, angle=45, anchor=tk.NW)
        
        # 绘制Y轴最大值标签
        self.canvas.create_text(x - 10, y + 30, text=str(max_value), font=self.font_config, anchor=tk.E)
    
    def fetch_and_display_stats(self):
        """获取数据、分析并显示统计结果"""
        identifier = self.id_entry.get().strip()
        if not identifier:
            messagebox.showwarning("警告", "请输入标识符")
            return
            
        # 获取数据
        data = self.fetch_data(identifier)
        if not data:
            return
            
        # 分析数据
        stats = self.analyze_data(data)
        if not stats:
            return
            
        # 显示结果
        self.display_text_stats(stats)
        self.draw_charts(stats)
        
        # 切换到第一个选项卡
        self.tab_control.select(0)
        
        self.status_var.set("统计完成")

if __name__ == "__main__":
    root = tk.Tk()
    app = ChuteStatsVisualizer(root)
    
    # 绑定窗口大小变化事件，重新绘制图表
    def on_resize(event):
        if hasattr(app, 'stats') and app.stats:
            app.draw_charts(app.stats)
    
    root.bind("<Configure>", on_resize)
    root.mainloop()